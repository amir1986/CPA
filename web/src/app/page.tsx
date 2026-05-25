import { redirect } from "next/navigation";

// Login flow removed — root always goes to /engagements.
export default function HomePage() {
  redirect("/engagements");
}
