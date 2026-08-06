import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Button from "@mui/material/Button";
import { ArticleCard, Article } from "../components/ArticleCard";

const DEFAULT_PAGE_SIZE = 20;
/** Mount window in which the WS replay burst renders cards at full opacity, so the whole history doesn't flash in on page load. */
const INITIAL_BURST_MS = 1000;

export function ArticleFeed({
  articles,
  onSelect,
  connected,
  pageSize = DEFAULT_PAGE_SIZE,
}: {
  articles: Article[];
  onSelect?: (id: string) => void;
  connected?: boolean;
  pageSize?: number;
}) {
  const [visibleCount, setVisibleCount] = useState(pageSize);
  const [inInitialBurst, setInInitialBurst] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setInInitialBurst(false), INITIAL_BURST_MS);
    return () => clearTimeout(t);
  }, []);

  if (articles.length === 0) {
    return (
      <Typography sx={{ color: "text.secondary", textAlign: "center", py: 4 }}>
        {connected === false || inInitialBurst ? "Connecting to broker…" : "No articles yet."}
      </Typography>
    );
  }

  const visible = articles.slice(0, visibleCount);
  const hasMore = visibleCount < articles.length;

  return (
    <Stack spacing={1.5}>
      <AnimatePresence mode="popLayout" initial={false}>
        {visible.map((a, i) => (
          <motion.div
            key={a.id}
            layout
            initial={inInitialBurst ? false : { opacity: 0, y: 10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, height: 0, marginBottom: 0 }}
            transition={{ duration: 0.3, delay: i * 0.02, ease: "easeOut" }}
          >
            <ArticleCard article={a} onSelect={onSelect} />
          </motion.div>
        ))}
      </AnimatePresence>
      {hasMore && (
        <Button
          variant="outlined"
          size="small"
          onClick={() => setVisibleCount((c) => c + pageSize)}
          sx={{ alignSelf: "center", minWidth: 220 }}
        >
          Load more ({articles.length - visibleCount} more)
        </Button>
      )}
    </Stack>
  );
}
