import { Chat } from "@/components/chat/chat";

export default function ChatPage() {
  return (
    <div className="mx-auto h-full max-w-4xl">
      <h1 className="mb-3 text-xl font-semibold">Chat</h1>
      <Chat />
    </div>
  );
}
