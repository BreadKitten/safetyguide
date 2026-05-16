export function MessageThread({ messages }) {
  return (
    <main className="mx-auto mt-2 max-w-4xl px-5">
      <div className="space-y-6" aria-live="polite">
        {messages.map((message) => {
          if (message.role === "user") {
            return <UserMessage key={message.id} text={message.text} />;
          }

          if (message.status === "loading") {
            return <ThinkingMessage key={message.id} />;
          }

          return (
            <AssistantMessage
              key={message.id}
              messageId={message.id}
              result={message.result}
            />
          );
        })}
      </div>
    </main>
  );
}

function UserMessage({ text }) {
  return (
    <div className="reveal flex justify-end">
      <div className="ui user-bubble max-w-[85%] whitespace-pre-wrap rounded-lg rounded-br-sm px-4 py-3 text-[15px] text-cream-50">
        {text}
      </div>
    </div>
  );
}

function ThinkingMessage() {
  return (
    <div className="reveal ui flex items-center gap-3 text-sage-700">
      <span className="breath" aria-hidden="true" />
      <span>Reading the preparedness guides...</span>
    </div>
  );
}

function AssistantMessage({ messageId, result }) {
  const citations = Array.isArray(result?.citations) ? result.citations : [];
  const gated = Boolean(result?.gated);

  return (
    <article className="reveal">
      <div className="ui mb-2 flex items-center gap-2 text-xs text-sage-700">
        <span className="inline-block h-2 w-2 rounded-full bg-sage-500" />
        <span className="font-medium uppercase tracking-wide">SafetyGuide</span>
        <ConfidenceBadge confidence={result?.confidence} gated={gated} />
      </div>

      {gated ? (
        <GatedBanner />
      ) : (
        <FormattedAnswer
          text={result?.answer || ""}
          citationsCount={citations.length}
          messageId={messageId}
        />
      )}

      <CitationsList citations={citations} messageId={messageId} />

      <div className="ui mt-4 text-xs text-sage-700">
        Always follow guidance from local authorities.
      </div>
    </article>
  );
}

function ConfidenceBadge({ confidence, gated }) {
  if (typeof confidence !== "number" || gated) {
    return null;
  }

  let label = "low match";
  let className = "bg-amber-100 text-amber-700";

  if (confidence >= 0.7) {
    label = "high confidence";
    className = "bg-sage-100 text-sage-900";
  } else if (confidence >= 0.3) {
    label = "partial match";
    className = "bg-cream-100 text-amber-700";
  }

  return (
    <span className={`ml-2 rounded-full px-2 py-0.5 text-[11px] ${className}`}>
      {label}
    </span>
  );
}

function GatedBanner() {
  return (
    <div className="ui mb-3 rounded-lg border border-amber-500/40 bg-amber-100 px-4 py-3 text-amber-700">
      <div className="mb-0.5 font-semibold">
        I could not find reliable information in the local emergency knowledge
        base.
      </div>
      <div className="text-sm">
        Try rephrasing your question, or for an active emergency call{" "}
        <a href="tel:911" className="underline">
          911
        </a>{" "}
        or contact your local emergency management office.
      </div>
    </div>
  );
}

function FormattedAnswer({ text, citationsCount, messageId }) {
  const blocks = String(text).trim().split(/\n{2,}/).filter(Boolean);

  if (!blocks.length) {
    return null;
  }

  return (
    <div className="prose-calm text-[17px] text-ink-900">
      {blocks.map((block, blockIndex) => {
        const lines = block
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean);
        const allBullets =
          lines.length > 1 && lines.every((line) => /^[-*]\s+/.test(line));
        const allNumbered =
          lines.length > 1 && lines.every((line) => /^\d+\.\s+/.test(line));

        if (allBullets) {
          return (
            <ul key={`${blockIndex}-${block}`} className="list-disc">
              {lines.map((line) => (
                <li key={line}>
                  <InlineCitations
                    text={line.replace(/^[-*]\s+/, "")}
                    citationsCount={citationsCount}
                    messageId={messageId}
                  />
                </li>
              ))}
            </ul>
          );
        }

        if (allNumbered) {
          return (
            <ol key={`${blockIndex}-${block}`} className="list-decimal">
              {lines.map((line) => (
                <li key={line}>
                  <InlineCitations
                    text={line.replace(/^\d+\.\s+/, "")}
                    citationsCount={citationsCount}
                    messageId={messageId}
                  />
                </li>
              ))}
            </ol>
          );
        }

        return (
          <p key={`${blockIndex}-${block}`}>
            <InlineCitations
              text={lines.join(" ")}
              citationsCount={citationsCount}
              messageId={messageId}
            />
          </p>
        );
      })}
    </div>
  );
}

function InlineCitations({ text, citationsCount, messageId }) {
  const parts = [];
  const regex = /\[(\d+)\]/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    const citationNumber = Number(match[1]);
    const marker = match[0];

    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    if (citationNumber > 0 && citationNumber <= citationsCount) {
      parts.push(
        <CitationLink
          key={`${messageId}-${citationNumber}-${match.index}`}
          citationNumber={citationNumber}
          messageId={messageId}
        />
      );
    } else {
      parts.push(marker);
    }

    lastIndex = match.index + marker.length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts;
}

function CitationLink({ citationNumber, messageId }) {
  const targetId = `cite-${messageId}-${citationNumber}`;

  return (
    <a
      href={`#${targetId}`}
      className="cite-mark"
      onClick={(event) => {
        const target = document.getElementById(targetId);

        if (!target) {
          return;
        }

        event.preventDefault();
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        target.classList.remove("cite-flash");
        window.requestAnimationFrame(() => {
          target.classList.add("cite-flash");
        });
      }}
    >
      {citationNumber}
    </a>
  );
}

function CitationsList({ citations, messageId }) {
  if (!citations.length) {
    return null;
  }

  return (
    <div className="ui mt-4 text-sm">
      <div className="mb-2 text-xs uppercase tracking-wider text-sage-700">
        Sources
      </div>
      <ol className="ml-5 list-decimal space-y-2">
        {citations.map((citation, index) => {
          const citationNumber = index + 1;
          const snippet =
            citation.snippet || (citation.text ? truncate(citation.text) : "");
          const meta = [
            citation.source,
            citation.section,
            citation.page && citation.page !== 1 ? `p. ${citation.page}` : null,
          ]
            .filter(Boolean)
            .join(" / ");

          return (
            <li
              key={`${messageId}-${citationNumber}-${citation.source || ""}`}
              id={`cite-${messageId}-${citationNumber}`}
              className="cite-target"
            >
              <div className="flex flex-wrap items-center gap-x-1 font-medium text-sage-900">
                <span>{citation.title || citation.source || "Source"}</span>
                {citation.disaster_type &&
                  citation.disaster_type !== "general" && (
                    <span className="type-tag">{citation.disaster_type}</span>
                  )}
              </div>
              {meta ? (
                <div className="text-xs text-sage-700">{meta}</div>
              ) : null}
              {snippet ? (
                <div className="mt-1 text-[13.5px] italic text-ink-700">
                  &quot;{snippet}&quot;
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function truncate(value, limit = 220) {
  const text = String(value).replace(/\s+/g, " ").trim();
  return text.length > limit
    ? `${text.slice(0, limit - 1).trimEnd()}...`
    : text;
}
