export function ChatComposer({
  disabled,
  draft,
  onDraftChange,
  onSubmit,
  textareaRef,
}) {
  return (
    <form
      className="composer-card reveal relative rounded-lg border border-sage-100 p-2"
      onSubmit={onSubmit}
    >
      <label htmlFor="safety-guide-question" className="sr-only">
        Ask a question
      </label>
      <textarea
        id="safety-guide-question"
        ref={textareaRef}
        rows={3}
        value={draft}
        disabled={disabled}
        className="ui w-full resize-none rounded-lg bg-transparent px-4 py-3 text-base text-ink-900 placeholder-sage-700/60 focus:outline-none disabled:cursor-not-allowed disabled:opacity-70"
        placeholder="For example: What should I do in the first minutes of a strong earthquake?"
        onChange={(event) => onDraftChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
      />
      <div className="ui flex flex-wrap items-center justify-between gap-3 px-2 pb-2 pt-1">
        <div className="text-xs text-sage-700">
          Press{" "}
          <kbd className="rounded border border-cream-200 bg-cream-100 px-1.5 py-0.5">
            Enter
          </kbd>{" "}
          to send /{" "}
          <kbd className="rounded border border-cream-200 bg-cream-100 px-1.5 py-0.5">
            Shift
          </kbd>
          +
          <kbd className="rounded border border-cream-200 bg-cream-100 px-1.5 py-0.5">
            Enter
          </kbd>{" "}
          for a new line
        </div>
        <button
          type="submit"
          disabled={disabled || !draft.trim()}
          className="send-btn inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium text-cream-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Ask SafetyGuide
          <span className="arrow" aria-hidden="true">
            -&gt;
          </span>
        </button>
      </div>
    </form>
  );
}
