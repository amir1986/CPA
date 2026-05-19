export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-elev px-4">
      <div className="w-full max-w-sm rounded-lg border border-border bg-bg p-8 shadow-e3">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-md bg-brand text-brand-fg font-bold">
            C
          </div>
          <div>
            <div className="text-base font-semibold leading-tight">CPA AI Assistant</div>
            <div className="text-xs text-fg-muted">Knowledge · Books · Analysis · Audit</div>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}
