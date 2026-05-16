import { STARTER_PROMPTS } from "@/lib/safety-guide/content";

export function StarterPrompts({ onSelect }) {
  return (
    <div className="ui mt-6 flex flex-wrap gap-2">
      {STARTER_PROMPTS.map((starter, index) => (
        <button
          key={starter}
          type="button"
          className="starter fade-in rounded-full border border-sage-100 bg-white/70 px-3.5 py-1.5 text-left text-sm text-sage-900 hover:bg-sage-50"
          style={{ animationDelay: `${120 * index}ms` }}
          onClick={() => onSelect(starter)}
        >
          {starter}
        </button>
      ))}
    </div>
  );
}
