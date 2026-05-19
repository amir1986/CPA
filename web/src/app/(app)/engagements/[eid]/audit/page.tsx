import { redirect } from "next/navigation";

type Props = { params: Promise<{ eid: string }> };

export default async function AuditIndex({ params }: Props) {
  const { eid } = await params;
  redirect(`/engagements/${eid}/audit/samples`);
}
