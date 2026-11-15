import { Suspense } from "react";
import BrowseWorkspace from "../browse-workspace";

export default function ExplorePage() {
  return <Suspense fallback={<p role="status">正在載入探索…</p>}>
    <BrowseWorkspace page="explore"/>
  </Suspense>;
}
