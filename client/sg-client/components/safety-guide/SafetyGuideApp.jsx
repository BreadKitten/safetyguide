'use client';

import { useEffect, useRef, useState } from 'react';
import { askSafetyGuide } from '@/lib/safety-guide/api';
import { AnimatedBackground } from './AnimatedBackground';
import { AppHeader } from './AppHeader';
import { ChatComposer } from './ChatComposer';
import { MessageThread } from './MessageThread';
import { SafetyAnchor } from './SafetyAnchor';
import { ScopeNote } from './ScopeNote';
import { StarterPrompts } from './StarterPrompts';

export function SafetyGuideApp() {
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState([]);
  const [isSending, setIsSending] = useState(false);
  const textareaRef = useRef(null);

  useEffect(() => {
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  async function handleSubmit(event) {
    event.preventDefault();

    const query = draft.trim();
    if (!query || isSending) {
      return;
    }

    const userMessage = {
      id: createId('user'),
      role: 'user',
      text: query,
    };
    const assistantMessage = {
      id: createId('assistant'),
      role: 'assistant',
      status: 'loading',
    };

    setDraft('');
    setIsSending(true);
    setMessages((currentMessages) => [
      ...currentMessages,
      userMessage,
      assistantMessage,
    ]);

    try {
      const result = await askSafetyGuide(query);
      setMessages((currentMessages) =>
        currentMessages.map((message) =>
          message.id === assistantMessage.id
            ? { ...message, status: 'done', result }
            : message,
        ),
      );
    } catch (error) {
      console.error(error);
      setMessages((currentMessages) =>
        currentMessages.map((message) =>
          message.id === assistantMessage.id
            ? {
                ...message,
                status: 'done',
                result: {
                  answer: '',
                  citations: [],
                  gated: true,
                  confidence: 0,
                },
              }
            : message,
        ),
      );
    } finally {
      setIsSending(false);
      textareaRef.current?.focus();
    }
  }

  function handleStarterSelect(starter) {
    setDraft(starter);
    textareaRef.current?.focus();
  }

  return (
    <>
      {/* <AnimatedBackground /> */}
      <SafetyAnchor />
      <AppHeader />
      <MessageThread messages={messages} />
      <section className='mx-auto mt-6 max-w-4xl px-5 pb-32'>
        <ChatComposer
          disabled={isSending}
          draft={draft}
          onDraftChange={setDraft}
          onSubmit={handleSubmit}
          textareaRef={textareaRef}
        />
        <StarterPrompts onSelect={handleStarterSelect} />
        <ScopeNote />
      </section>
    </>
  );
}

function createId(prefix) {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
