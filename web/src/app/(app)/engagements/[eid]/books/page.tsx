import { redirect } from "next/navigation";

type Props = { params: Promise<{ eid: string }> };

export default async function BooksIndex({ params }: Props) {
  const { eid } = await params;
  redirect(`/engagements/${eid}/books/trial-balance`);
}
