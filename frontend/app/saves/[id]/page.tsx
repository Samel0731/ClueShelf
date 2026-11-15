import { Suspense } from "react";
import SaveDetail from "./save-detail";

export default async function SavePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Suspense fallback={<p role="status">正在讀取收藏…</p>}>
    <SaveDetail key={id} id={id}/>
  </Suspense>;
}
