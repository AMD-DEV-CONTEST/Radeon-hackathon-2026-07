import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Typography from "@mui/material/Typography";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Box from "@mui/material/Box";
import AutoAwesome from "@mui/icons-material/AutoAwesome";
import { TrustRing } from "./TrustRing";
import { SignatureStatus } from "./SignatureStatus";

export interface Article {
  id: string;
  type: string;
  content: string;
  payload?: Record<string, unknown>;
  trust_score?: number | null;
  agent_signature?: string | null;
  org_signature?: string | null;
  cites?: string[];
  src_org?: string;
}

const TYPE_COLORS: Record<string, "error" | "secondary" | "warning" | "info" | "success"> = {
  finding: "error",
  insight: "secondary",
  warning: "warning",
  precedent: "info",
  procedure: "success",
};

const ORG_LABELS: Record<string, string> = {
  "did:percq:org:soc-alpha": "SOC Alpha",
  "did:percq:org:soc-beta": "SOC Beta",
};

const ORG_COLORS: Record<string, "info" | "warning"> = {
  "did:percq:org:soc-alpha": "info",
  "did:percq:org:soc-beta": "warning",
};

export function ArticleCard({ article, onSelect }: { article: Article; onSelect?: (id: string) => void }) {
  const orgLabel = ORG_LABELS[article.src_org || ""] || "";
  const orgColor = ORG_COLORS[article.src_org || ""] || "default";
  const tactic = article.payload?.tactic as string | undefined;
  const technique = article.payload?.technique_id as string | undefined;
  const threatActor = article.payload?.threat_actor as string | undefined;

  const isLlmDerived = (article.type === "insight" || article.type === "warning")
    && article.cites != null && article.cites.length > 0;

  return (
    <Card variant="outlined" sx={{ borderRadius: 2, p: 1 }}>
      <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
        <Stack direction="row" spacing={1.5} alignItems="flex-start">
          <TrustRing pct={article.trust_score ?? 0} />
          <Box sx={{ flex: 1 }}>
            <Stack direction="row" spacing={0.5} sx={{ flexWrap: "wrap", mb: 0.5 }}>
              <Chip label={article.type} size="small" color={TYPE_COLORS[article.type] || "default"} />
              {orgLabel && <Chip label={orgLabel} size="small" color={orgColor as "info" | "warning"} variant="outlined" />}
              {technique && <Chip label={technique} size="small" variant="outlined" />}
              {tactic && <Chip label={tactic} size="small" variant="outlined" sx={{ opacity: 0.7 }} />}
              {isLlmDerived && (
                <Chip icon={<AutoAwesome sx={{ fontSize: 12 }} />} label="LLM-synthesized" size="small" color="secondary" variant="outlined" />
              )}
              {article.agent_signature && <SignatureStatus sig={article.agent_signature} label="agent" />}
              {article.org_signature && <SignatureStatus sig={article.org_signature} label="org" />}
            </Stack>
            {threatActor && (
              <Typography variant="caption" sx={{ color: "text.secondary", display: "block", mb: 0.25 }}>
                Actor: {threatActor}
              </Typography>
            )}
            <Typography variant="body2" sx={{
              overflow: "hidden",
              textOverflow: "ellipsis",
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
            }}>
              {article.content}
            </Typography>
            {article.cites && article.cites.length > 0 && (
              <Typography variant="caption" sx={{ color: "text.secondary", display: "block", mt: 0.5 }}>
                Cites {article.cites.length} article{article.cites.length > 1 ? "s" : ""}
              </Typography>
            )}
          </Box>
          {onSelect && (
            <Button variant="text" size="small" onClick={() => onSelect(article.id)} sx={{ flexShrink: 0 }}>
              detail
            </Button>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
