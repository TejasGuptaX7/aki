// aki-mcp-mac — minimal Model Context Protocol server over stdio.
//
// Exposes a small set of macOS-only tools for the local Aki desktop's
// embedded Hermes to call:
//
//   - calendar.today_events      (EventKit via osascript)
//   - mail.unread_count          (Mail.app via osascript)
//   - notes.append               (Notes.app via osascript)
//   - shell.exec                 (whitelisted commands only — `ls`, `pwd`,
//                                 `date`, `whoami`, `git status`)
//
// Protocol: JSON-RPC 2.0 over stdin/stdout, one message per line. MCP's
// `initialize`, `tools/list`, and `tools/call` methods are implemented.
// We skip prompts/resources/notifications for the scaffold.
//
// Invoked by Hermes via its mcp_servers config:
//   {
//     "name": "macos",
//     "transport": "stdio",
//     "command": "aki-mcp-mac",
//     "args": []
//   }

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};
use std::process::Command;

const PROTOCOL_VERSION: &str = "2024-11-05";
const SERVER_NAME: &str = "aki-mcp-mac";
const SERVER_VERSION: &str = "0.1.0";

#[derive(Debug, Deserialize)]
struct Request {
    jsonrpc: String,
    id: Option<Value>,
    method: String,
    #[serde(default)]
    params: Value,
}

#[derive(Debug, Serialize)]
struct Response<'a> {
    jsonrpc: &'a str,
    id: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<RpcError>,
}

#[derive(Debug, Serialize)]
struct RpcError {
    code: i32,
    message: String,
}

fn err(id: Value, code: i32, message: &str) -> Response<'static> {
    Response {
        jsonrpc: "2.0",
        id,
        result: None,
        error: Some(RpcError {
            code,
            message: message.to_string(),
        }),
    }
}

fn ok(id: Value, result: Value) -> Response<'static> {
    Response {
        jsonrpc: "2.0",
        id,
        result: Some(result),
        error: None,
    }
}

fn tools_definition() -> Value {
    json!([
        {
            "name": "calendar.today_events",
            "description": "List today's calendar events from macOS Calendar.app.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "mail.unread_count",
            "description": "Return the count of unread messages in Mail.app inbox.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "notes.append",
            "description": "Append a line to the user's default Notes.app note named 'Aki'.",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
        {
            "name": "shell.exec",
            "description": "Run a whitelisted shell command. Allowed: ls, pwd, date, whoami, git status.",
            "inputSchema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    ])
}

fn handle(req: Request) -> Option<Response<'static>> {
    let id = req.id.clone().unwrap_or(Value::Null);

    match req.method.as_str() {
        "initialize" => Some(ok(
            id,
            json!({
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "capabilities": {"tools": {}},
            }),
        )),
        "tools/list" => Some(ok(id, json!({"tools": tools_definition()}))),
        "tools/call" => {
            let name = req.params.get("name").and_then(|v| v.as_str()).unwrap_or("");
            let args = req.params.get("arguments").cloned().unwrap_or(json!({}));
            match call_tool(name, &args) {
                Ok(text) => Some(ok(
                    id,
                    json!({"content": [{"type": "text", "text": text}]}),
                )),
                Err(e) => Some(err(id, -32603, &format!("tool error: {e}"))),
            }
        }
        // Notifications (no id) don't get a response.
        _ if req.id.is_none() => None,
        _ => Some(err(id, -32601, &format!("method not found: {}", req.method))),
    }
}

fn call_tool(name: &str, args: &Value) -> Result<String, String> {
    match name {
        "calendar.today_events" => osascript(
            r#"
            set output to ""
            tell application "Calendar"
                set todayStart to current date
                set hours of todayStart to 0
                set minutes of todayStart to 0
                set seconds of todayStart to 0
                set todayEnd to todayStart + (24 * hours)
                repeat with cal in calendars
                    set evs to (every event of cal whose start date is greater than or equal to todayStart and start date is less than todayEnd)
                    repeat with ev in evs
                        set output to output & (summary of ev) & " — " & (start date of ev as text) & linefeed
                    end repeat
                end repeat
            end tell
            return output
            "#,
        ),
        "mail.unread_count" => osascript(
            r#"tell application "Mail" to return unread count of inbox"#,
        ),
        "notes.append" => {
            let text = args.get("text").and_then(|v| v.as_str()).unwrap_or("");
            if text.is_empty() {
                return Err("text is required".into());
            }
            let escaped = text.replace('\\', "\\\\").replace('"', "\\\"");
            let script = format!(
                r#"
                tell application "Notes"
                    set noteName to "Aki"
                    set targetNote to missing value
                    repeat with n in notes
                        if name of n is noteName then
                            set targetNote to n
                            exit repeat
                        end if
                    end repeat
                    if targetNote is missing value then
                        set targetNote to make new note with properties {{name:noteName, body:"{}"}}
                    else
                        set body of targetNote to (body of targetNote) & return & "{}"
                    end if
                    return "ok"
                end tell
                "#,
                escaped, escaped
            );
            osascript(&script)
        }
        "shell.exec" => {
            let command = args
                .get("command")
                .and_then(|v| v.as_str())
                .ok_or("command is required")?;
            run_whitelisted_shell(command)
        }
        _ => Err(format!("unknown tool: {name}")),
    }
}

fn osascript(script: &str) -> Result<String, String> {
    let out = Command::new("osascript")
        .args(["-e", script])
        .output()
        .map_err(|e| format!("osascript spawn: {e}"))?;
    if !out.status.success() {
        return Err(format!(
            "osascript failed: {}",
            String::from_utf8_lossy(&out.stderr)
        ));
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn run_whitelisted_shell(command: &str) -> Result<String, String> {
    const ALLOWED: &[&str] = &["ls", "pwd", "date", "whoami", "git status"];
    let cmd = command.trim();
    if !ALLOWED.iter().any(|a| cmd == *a || cmd.starts_with(&format!("{a} "))) {
        return Err(format!(
            "command not in whitelist (allowed: {})",
            ALLOWED.join(", ")
        ));
    }
    let out = Command::new("/bin/sh")
        .args(["-c", cmd])
        .output()
        .map_err(|e| format!("shell spawn: {e}"))?;
    if !out.status.success() {
        return Err(format!("shell failed: {}", String::from_utf8_lossy(&out.stderr)));
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn main() {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) if !l.trim().is_empty() => l,
            Ok(_) => continue,
            Err(_) => break,
        };
        match serde_json::from_str::<Request>(&line) {
            Ok(req) if req.jsonrpc == "2.0" => {
                if let Some(resp) = handle(req) {
                    let body = serde_json::to_string(&resp).unwrap_or_default();
                    let _ = writeln!(out, "{body}");
                    let _ = out.flush();
                }
            }
            Ok(_) | Err(_) => {
                // Best-effort: ignore malformed lines. Errors with an id
                // require parsing; if we can't parse at all, the client
                // will time out anyway.
            }
        }
    }
}
