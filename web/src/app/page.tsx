import { redirect } from "next/navigation";

export default function HomePage() {
  // Phase 1: no real session check yet — send everyone through the login
  // flow. Once Auth.js is fully wired, this will branch on session presence.
  redirect("/login");
}
