This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://github.com/vercel/next.js/tree/canary/packages/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

## Backend connection

The chat UI calls `lib/safety-guide/api.js`. To connect a real backend, create
`.env.local` and point the client at your chat endpoint:

```bash
NEXT_PUBLIC_SAFETY_GUIDE_ENDPOINT=http://localhost:8000/chat
```

The endpoint should accept `POST { "query": "..." }` and return:

```json
{
  "answer": "text with [1] citation markers",
  "citations": [{ "source": "Ready.gov", "page": 1, "text": "..." }],
  "gated": false,
  "confidence": 0.92
}
```

If the env var is not set, the frontend uses a local dev stub.

The screen is split across `components/safety-guide`, while backend wiring lives
in `lib/safety-guide/api.js`.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
