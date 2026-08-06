import { useEffect, useRef } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { Network } from "vis-network";
import { DataSet } from "vis-data";

export function ProvenanceGraph({ articles }: { articles: any[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || articles.length === 0) return;
    const nodes = new DataSet(articles.map(a => ({
      id: a.id,
      label: a.content?.substring(0, 30) || a.id.substring(0, 10),
      title: a.content,
      shape: "box",
      color: {
        background: a.type === "insight" ? "#9775fa" : a.type === "warning" ? "#f76707" : "#e03131",
        border: "#1a1b1e",
      },
    })));
    const edges = new DataSet(
      articles.filter(a => a.cites).flatMap((a: any) => (a.cites || []).map((c: string) => ({ from: a.id, to: c, arrows: "to" })))
    );
    const network = new Network(containerRef.current, { nodes, edges }, {
      physics: { solver: "forceAtlas2Based", forceAtlas2Based: { gravitationalConstant: -40 } },
      edges: { arrows: { to: { enabled: true } }, color: { color: "#5c5f66" } },
    });
    return () => network.destroy();
  }, [articles]);

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 3, fontWeight: 700 }}>Provenance Graph</Typography>
      <Box sx={{ border: "1px solid", borderColor: "divider", borderRadius: 3, overflow: "hidden" }}>
        <Box ref={containerRef} sx={{ height: 600 }} />
      </Box>
    </Box>
  );
}
