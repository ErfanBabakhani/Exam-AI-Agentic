import { GradingDetailPage } from "@/components/grading-detail-page";


export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <GradingDetailPage gradingId={id} />;
}
