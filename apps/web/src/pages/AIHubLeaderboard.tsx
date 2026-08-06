import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Bot, ArrowLeft, Download, Heart, TrendingUp, Trophy, Medal, Award, Loader2 } from 'lucide-react';
import { publicJson } from '../lib/auth';

interface HubModel {
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
}

type SortField = 'downloads' | 'likes' | 'lastModified';

export function AIHubLeaderboard() {
  const navigate = useNavigate();
  const [models, setModels] = useState<HubModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<SortField>('downloads');

  const loadModels = useCallback(async (sort: SortField) => {
    setLoading(true);
    try {
      const data = await publicJson<{ items: HubModel[] }>(
        `/api/v1/hub/models?tag=robotics&sort=${sort}&limit=30`
      );
      setModels(data.items);
    } catch {
      setModels([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadModels(sortBy);
  }, [loadModels, sortBy]);

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

  const getRankIcon = (rank: number) => {
    if (rank === 1) return <Trophy className="h-5 w-5 text-yellow-500" />;
    if (rank === 2) return <Medal className="h-5 w-5 text-gray-400" />;
    if (rank === 3) return <Medal className="h-5 w-5 text-amber-600" />;
    return <span className="w-5 text-center font-medium text-muted-foreground">{rank}</span>;
  };

  const getRankStyle = (rank: number) => {
    if (rank === 1) return 'bg-yellow-500/10 border-yellow-500/30';
    if (rank === 2) return 'bg-gray-400/10 border-gray-400/30';
    if (rank === 3) return 'bg-amber-600/10 border-amber-600/30';
    return '';
  };

  const totalDownloads = models.reduce((acc, m) => acc + m.downloads, 0);
  const totalLikes = models.reduce((acc, m) => acc + m.likes, 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => navigate('/ai-hub')}>
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back
          </Button>
          <div>
            <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
              <TrendingUp className="h-8 w-8 text-primary" />
              Leaderboard
            </h1>
            <p className="text-muted-foreground mt-1">
              Top performing robot learning models from HuggingFace
            </p>
          </div>
        </div>
      </div>

      <Card>
        <CardContent className="p-2">
          <div className="flex flex-wrap gap-2">
            <Button
              variant={sortBy === 'downloads' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setSortBy('downloads')}
              className="flex-1 md:flex-none"
            >
              <Download className="h-4 w-4 mr-2" />
              Most Downloaded
            </Button>
            <Button
              variant={sortBy === 'likes' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setSortBy('likes')}
              className="flex-1 md:flex-none"
            >
              <Heart className="h-4 w-4 mr-2" />
              Most Liked
            </Button>
            <Button
              variant={sortBy === 'lastModified' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setSortBy('lastModified')}
              className="flex-1 md:flex-none"
            >
              <Award className="h-4 w-4 mr-2" />
              Recently Updated
            </Button>
          </div>
        </CardContent>
      </Card>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground w-16">Rank</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Model</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Tags</th>
                    <th className="px-4 py-3 text-right text-sm font-medium text-muted-foreground">Downloads</th>
                    <th className="px-4 py-3 text-right text-sm font-medium text-muted-foreground">Likes</th>
                    <th className="px-4 py-3 text-right text-sm font-medium text-muted-foreground">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((model, index) => (
                    <tr
                      key={model.repo_id}
                      className={`border-b last:border-0 hover:bg-muted/50 cursor-pointer transition-colors ${getRankStyle(index + 1)}`}
                      onClick={() => navigate(`/ai-hub/model/${encodeURIComponent(model.repo_id)}`)}
                    >
                      <td className="px-4 py-4">
                        <div className="flex items-center justify-center">{getRankIcon(index + 1)}</div>
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-3">
                          <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center"><Bot className="h-5 w-5 text-primary" /></div>
                          <div>
                            <p className="font-medium">{model.name}</p>
                            <p className="text-sm text-muted-foreground">by {model.author}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex flex-wrap gap-1">
                          {model.tags.slice(0, 3).map((tag) => (
                            <Badge key={tag} variant="outline" className="text-xs">{tag}</Badge>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-4 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Download className="h-4 w-4 text-muted-foreground" />
                          <span className="font-medium">{formatNumber(model.downloads)}</span>
                        </div>
                      </td>
                      <td className="px-4 py-4 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Heart className="h-4 w-4 text-muted-foreground" />
                          <span className="font-medium">{formatNumber(model.likes)}</span>
                        </div>
                      </td>
                      <td className="px-4 py-4 text-right text-sm text-muted-foreground">
                        {formatDate(model.updated_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total Models</p>
                <p className="text-3xl font-bold">{models.length}</p>
              </div>
              <div className="h-12 w-12 rounded-xl bg-primary/10 flex items-center justify-center">
                <Trophy className="h-6 w-6 text-primary" />
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total Downloads</p>
                <p className="text-3xl font-bold">{formatNumber(totalDownloads)}</p>
              </div>
              <div className="h-12 w-12 rounded-xl bg-green-500/10 flex items-center justify-center">
                <Download className="h-6 w-6 text-green-500" />
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total Likes</p>
                <p className="text-3xl font-bold">{formatNumber(totalLikes)}</p>
              </div>
              <div className="h-12 w-12 rounded-xl bg-red-500/10 flex items-center justify-center">
                <Heart className="h-6 w-6 text-red-500" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
