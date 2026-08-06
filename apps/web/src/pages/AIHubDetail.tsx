import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Bot, Download, Heart, ArrowLeft, Copy, ExternalLink, CheckCircle } from 'lucide-react';
import { publicJson } from '../lib/auth';

interface HubModelDetail {
  repo_id: string;
  author: string;
  name: string;
  description: string;
  tags: string[];
  downloads: number;
  likes: number;
  created_at: string;
  updated_at: string;
  size: string;
  task_type: string;
  robot_type: string;
  compatible_skills: string[];
  readme?: string;
}

export function AIHubDetail() {
  const { repo_id } = useParams<{ repo_id: string }>();
  const navigate = useNavigate();
  const [model, setModel] = useState<HubModelDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (repo_id) {
      fetchModelDetail(decodeURIComponent(repo_id));
    }
  }, [repo_id]);

  const fetchModelDetail = async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await publicJson<HubModelDetail>(`/api/v1/hub/models/${id}`);
      setModel(data);
    } catch (e) {
      // Don't fabricate a placeholder model — surface the real error so the
      // user knows the API call failed. Previous behavior stuffed a fake
      // HubModelDetail with "Could not load model details." which still
      // rendered the rest of the page (with hardcoded README + Similar
      // Models) as if the data were real.
      setError((e as Error).message);
      setModel(null);
    } finally {
      setLoading(false);
    }
  };

  const handleCopyId = () => {
    if (model) {
      navigator.clipboard.writeText(model.repo_id);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleOpenHF = () => {
    if (model) {
      window.open(`https://huggingface.co/${model.repo_id}`, '_blank');
    }
  };

  const formatNumber = (num: number) => {
    if (num >= 1000) return `${(num / 1000).toFixed(1)}k`;
    return num.toString();
  };

  const formatDate = (dateStr: string) => {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return dateStr;
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin h-8 w-8 border-2 border-primary border-t-transparent rounded-full" />
      </div>
    );
  }

  if (!model) {
    return (
      <div className="text-center py-12">
        <div className="text-4xl mb-4">❌</div>
        <h3 className="text-lg font-medium mb-2">Model not found</h3>
        {error && <p className="text-sm text-muted-foreground mb-4">{error}</p>}
        <Button onClick={() => navigate('/ai-hub')}>Back to AI Hub</Button>
      </div>
    );
  }

  const hfUrl = `https://huggingface.co/${model.repo_id}`;

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <Button variant="ghost" size="sm" onClick={() => navigate('/ai-hub')}>
          <ArrowLeft className="h-4 w-4 mr-1" />
          AI Hub
        </Button>
        <span className="text-muted-foreground">/</span>
        <span className="text-muted-foreground truncate max-w-xs">{model.name}</span>
      </div>

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-start gap-6">
        <div className="h-20 w-20 rounded-2xl bg-primary/10 flex items-center justify-center text-4xl">
          <Bot className="h-5 w-5" />
        </div>
        <div className="flex-1">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold">{model.name}</h1>
              <p className="text-muted-foreground mt-1">
                by <span className="text-primary">{model.author}</span>
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={handleCopyId}>
                {copied ? (
                  <>
                    <CheckCircle className="h-4 w-4 mr-1.5" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy className="h-4 w-4 mr-1.5" />
                    Copy ID
                  </>
                )}
              </Button>
              <Button variant="outline" size="sm" onClick={handleOpenHF}>
                <ExternalLink className="h-4 w-4 mr-1.5" />
                View on HF
              </Button>
            </div>
          </div>

          <p className="text-muted-foreground mt-4 max-w-2xl">{model.description}</p>

          <div className="flex flex-wrap items-center gap-4 mt-4">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-sm px-3 py-1">
                {model.robot_type}
              </Badge>
              <Badge variant="outline" className="text-sm px-3 py-1">
                {model.task_type}
              </Badge>
            </div>
            <div className="flex items-center gap-4 text-sm text-muted-foreground">
              <span className="flex items-center gap-1">
                <Download className="h-4 w-4" />
                {formatNumber(model.downloads)} downloads
              </span>
              <span className="flex items-center gap-1">
                <Heart className="h-4 w-4" />
                {formatNumber(model.likes)} likes
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Content */}
        <div className="lg:col-span-2 space-y-6">
          {/* README */}
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold">README</h2>
                <Button variant="ghost" size="sm" onClick={handleOpenHF}>
                  <ExternalLink className="h-4 w-4 mr-1.5" />
                  Open on HuggingFace
                </Button>
              </div>
              {model.readme ? (
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  <pre className="whitespace-pre-wrap text-xs bg-muted p-3 rounded-md overflow-x-auto">
                    {model.readme}
                  </pre>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground space-y-2">
                  <p>README 未通过 BotverseX API 提供。</p>
                  <p>
                    请前往 HuggingFace 原页查看完整模型卡：
                    <a
                      href={hfUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-1 text-primary underline"
                    >
                      {hfUrl}
                    </a>
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Tags */}
          <Card>
            <CardContent className="p-6">
              <h2 className="text-lg font-semibold mb-4">Tags</h2>
              {model.tags.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {model.tags.map((tag) => (
                    <Badge key={tag} variant="secondary" className="px-3 py-1">
                      {tag}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">无标签</p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Download Card — disabled, no backend route exists */}
          <Card>
            <CardContent className="p-6 space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Model Size</span>
                <span className="font-medium">{model.size || '—'}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Created</span>
                <span className="font-medium">{formatDate(model.created_at)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Updated</span>
                <span className="font-medium">{formatDate(model.updated_at)}</span>
              </div>
              <div className="pt-4 border-t space-y-2">
                <Button
                  className="w-full"
                  size="lg"
                  disabled
                  title="BotverseX 内部下载通道暂未开放，请前往 HuggingFace 下载"
                >
                  <Download className="h-4 w-4 mr-2" />
                  暂未开放
                </Button>
                <Button
                  variant="outline"
                  className="w-full"
                  size="sm"
                  onClick={handleOpenHF}
                >
                  <ExternalLink className="h-4 w-4 mr-2" />
                  前往 HuggingFace 下载
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Like — kept as visual indicator only, no fake backend call */}
          <Card>
            <CardContent className="p-6 space-y-3">
              <Button
                variant="outline"
                className="w-full justify-start pointer-events-none opacity-60"
                title="点赞数据来自 HuggingFace，请前往原页操作"
              >
                <Heart className="h-4 w-4 mr-2" />
                Like（前往 HF 操作）
              </Button>
            </CardContent>
          </Card>

          {/* Similar Models — removed (was hardcoded fake list) */}
        </div>
      </div>
    </div>
  );
}
