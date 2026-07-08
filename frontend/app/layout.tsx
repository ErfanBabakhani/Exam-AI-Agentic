import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Zanista Exam Grader",
  description: "Authenticated frontend for the Django-based AI exam grader."
};


export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
