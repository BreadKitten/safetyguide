import "./globals.css";

export const metadata = {
  title: "SafetyGuide - Offline Disaster Relief Assistant",
  description:
    "A local-first disaster preparedness assistant grounded in emergency guidance sources.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
