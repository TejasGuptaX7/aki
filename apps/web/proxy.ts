/**
 * Clerk middleware — Next 16 renamed `middleware.ts` to `proxy.ts`. The
 * function we export is still `clerkMiddleware`.
 *
 * /connect and /chat require sign-in; everything else (landing, sign-in,
 * sign-up routes) is public.
 */
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isProtected = createRouteMatcher(["/connect(.*)", "/chat(.*)"]);

export default clerkMiddleware(async (auth, req) => {
  if (isProtected(req)) {
    await auth.protect();
  }
});

export const config = {
  matcher: [
    // Skip Next.js internals and all static files.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
