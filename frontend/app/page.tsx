import { Suspense } from "react";
import { redirect } from "next/navigation";
import BrowseWorkspace from "./browse-workspace";

export default async function Home({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { youtube } = await searchParams;
  if (youtube === "connected" || youtube === "denied" || youtube === "error") {
    redirect(`/settings?youtube=${youtube}`);
  }
  return <Suspense fallback={<p role="status">正在載入收藏庫…</p>}>
    <BrowseWorkspace page="library"/>
  </Suspense>;
}
