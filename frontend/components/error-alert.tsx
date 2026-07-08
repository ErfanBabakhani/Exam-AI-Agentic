import { TransientMessage } from "@/components/transient-message";

export function ErrorAlert({ message }: { message: string }) {
  return <TransientMessage message={message} tone="error" />;
}
