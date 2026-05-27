import { Chat } from "@/components/chat/chat";
import { t } from "@/lib/i18n";
import { getLocale } from "@/lib/i18n/server";

export default async function ChatPage() {
  const locale = await getLocale();
  return (
    <div className="mx-auto h-full max-w-4xl">
      <h1 className="mb-3 text-xl font-semibold">{t("chat.title", locale)}</h1>
      <Chat />
    </div>
  );
}
