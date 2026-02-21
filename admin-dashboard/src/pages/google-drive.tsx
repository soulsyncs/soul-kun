/**
 * Google Drive管理ページ
 *
 * DBに取り込み済みのDriveファイルを一覧表示・検索・ダウンロード・アップロードできる。
 * 閲覧: Level 5以上（管理者）
 * アップロード: Level 6以上（代表/CFO）
 */

import { useState, useRef } from 'react';
import {
  HardDrive,
  RefreshCw,
  Search,
  Download,
  ExternalLink,
  Upload,
  X,
  AlertTriangle,
  FileText,
  File,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useAuth } from '@/hooks/use-auth';
import {
  useDriveFiles,
  useDriveSyncStatus,
  useDownloadDriveFile,
  useUploadDriveFile,
  type DriveFilters,
} from '@/hooks/use-drive';

// ──────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────

function formatFileSize(bytes: number | null): string {
  if (!bytes) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleDateString('ja-JP', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

// W-2 fix: Validate URL scheme before using as href (XSS防止)
function isSafeUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  try {
    return new URL(url).protocol === 'https:';
  } catch {
    return false;
  }
}

function getFileIcon(fileType: string | null) {
  if (!fileType) return <File className="h-4 w-4 text-muted-foreground" />;
  const t = fileType.toLowerCase();
  if (t === 'pdf') return <FileText className="h-4 w-4 text-red-500" />;
  if (['docx', 'doc', 'document'].includes(t))
    return <FileText className="h-4 w-4 text-blue-600" />;
  if (['xlsx', 'xls', 'spreadsheet'].includes(t))
    return <FileText className="h-4 w-4 text-green-600" />;
  if (['pptx', 'ppt', 'presentation'].includes(t))
    return <FileText className="h-4 w-4 text-orange-500" />;
  return <File className="h-4 w-4 text-muted-foreground" />;
}

const CLASSIFICATION_CONFIG: Record<
  string,
  { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline'; className: string }
> = {
  public: { label: '公開', variant: 'default', className: 'bg-green-100 text-green-800 border-green-200' },
  internal: { label: '社内', variant: 'default', className: 'bg-blue-100 text-blue-800 border-blue-200' },
  restricted: { label: '制限', variant: 'default', className: 'bg-yellow-100 text-yellow-800 border-yellow-200' },
  confidential: { label: '機密', variant: 'destructive', className: 'bg-red-100 text-red-800 border-red-200' },
};

const STATUS_CONFIG: Record<
  string,
  { label: string; icon: React.ReactNode }
> = {
  completed: { label: '処理済み', icon: <CheckCircle2 className="h-3.5 w-3.5 text-green-600" /> },
  failed: { label: 'エラー', icon: <XCircle className="h-3.5 w-3.5 text-red-500" /> },
  processing: { label: '処理中', icon: <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" /> },
  pending: { label: '待機中', icon: <Loader2 className="h-3.5 w-3.5 text-muted-foreground" /> },
};

// ──────────────────────────────────────────────
// Upload Modal
// ──────────────────────────────────────────────

const ALLOWED_EXTENSIONS = ['pdf', 'docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt', 'txt', 'md', 'csv'];
const MAX_SIZE_MB = 20;

interface UploadModalProps {
  onClose: () => void;
}

function UploadModal({ onClose }: UploadModalProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [classification, setClassification] = useState('internal');
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { mutate: upload, isPending, isSuccess, uploadProgress } = useUploadDriveFile();

  function handleFilePick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      setError(`許可されていないファイル形式です（${ALLOWED_EXTENSIONS.join(', ')}のみ）`);
      return;
    }
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      setError(`ファイルサイズが${MAX_SIZE_MB}MBを超えています`);
      return;
    }
    setSelectedFile(file);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    // simulate change event validation
    const fakeEvt = { target: { files: [file] } } as unknown as React.ChangeEvent<HTMLInputElement>;
    handleFilePick(fakeEvt);
  }

  function handleSubmit() {
    if (!selectedFile || !classification) return;
    setError(null);
    upload(
      { file: selectedFile, classification },
      {
        onError: (err) => setError(err instanceof Error ? err.message : 'アップロードに失敗しました'),
      }
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg bg-card p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Driveへアップロード</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:bg-accent"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {isSuccess ? (
          <div className="flex flex-col items-center gap-3 py-6">
            <CheckCircle2 className="h-12 w-12 text-green-500" />
            <p className="font-medium">アップロード完了！</p>
            <p className="text-sm text-muted-foreground">ファイル一覧に反映されました</p>
            <Button onClick={onClose}>閉じる</Button>
          </div>
        ) : (
          <>
            {/* Drop zone */}
            <div
              className="mb-4 flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted-foreground/30 p-8 hover:border-primary/50 cursor-pointer"
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
            >
              <Upload className="mb-2 h-8 w-8 text-muted-foreground" />
              {selectedFile ? (
                <p className="text-sm font-medium">{selectedFile.name}</p>
              ) : (
                <>
                  <p className="text-sm text-muted-foreground">クリックまたはドラッグ&ドロップ</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {ALLOWED_EXTENSIONS.join(', ')} / 最大{MAX_SIZE_MB}MB
                  </p>
                </>
              )}
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                accept={ALLOWED_EXTENSIONS.map((e) => `.${e}`).join(',')}
                onChange={handleFilePick}
              />
            </div>

            {/* Classification */}
            <div className="mb-4">
              <label className="mb-1.5 block text-sm font-medium">機密レベル（必須）</label>
              <Select value={classification} onValueChange={setClassification}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="public">公開</SelectItem>
                  <SelectItem value="internal">社内</SelectItem>
                  <SelectItem value="restricted">制限</SelectItem>
                  <SelectItem value="confidential">機密</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Error */}
            {error && (
              <div className="mb-4 flex items-start gap-2 rounded-md bg-red-50 p-3 text-sm text-red-700">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                {error}
              </div>
            )}

            {/* Progress */}
            {isPending && (
              <div className="mb-4">
                <div className="h-2 w-full rounded-full bg-muted">
                  <div
                    className="h-2 rounded-full bg-primary transition-all"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
                <p className="mt-1 text-xs text-muted-foreground text-right">
                  {uploadProgress}%
                </p>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={onClose} disabled={isPending}>
                キャンセル
              </Button>
              <Button
                onClick={handleSubmit}
                disabled={!selectedFile || isPending}
              >
                {isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="mr-2 h-4 w-4" />
                )}
                アップロード
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────
// Main Page
// ──────────────────────────────────────────────

const PER_PAGE = 20;

export function GoogleDrivePage() {
  const { user } = useAuth();
  const canUpload = (user?.role_level ?? 0) >= 6;

  const [filters, setFilters] = useState<DriveFilters>({ page: 1, per_page: PER_PAGE });
  const [keyword, setKeyword] = useState('');
  const [showUpload, setShowUpload] = useState(false);

  const { data: filesData, isLoading: filesLoading, refetch } = useDriveFiles(filters);
  const { data: syncData } = useDriveSyncStatus();
  const { mutate: download, isPending: downloading } = useDownloadDriveFile();

  function applyFilters() {
    setFilters((prev) => ({ ...prev, q: keyword || undefined, page: 1 }));
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') applyFilters();
  }

  const totalPages = filesData ? Math.ceil(filesData.total / PER_PAGE) : 1;
  const currentPage = filters.page ?? 1;

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* ── Header ── */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold">
              <HardDrive className="h-6 w-6" />
              Driveファイル管理
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Google Driveに取り込まれたファイルを管理します
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="mr-1 h-4 w-4" />
              更新
            </Button>
            {canUpload && (
              <Button size="sm" onClick={() => setShowUpload(true)}>
                <Upload className="mr-1 h-4 w-4" />
                アップロード
              </Button>
            )}
          </div>
        </div>

        {/* ── Sync Status Bar ── */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Card>
            <CardContent className="flex items-center gap-3 p-4">
              <HardDrive className="h-8 w-8 text-primary" />
              <div>
                <p className="text-xs text-muted-foreground">総ファイル数</p>
                <p className="text-xl font-bold">
                  {syncData?.total_files ?? '-'}
                </p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex items-center gap-3 p-4">
              <CheckCircle2 className="h-8 w-8 text-green-500" />
              <div>
                <p className="text-xs text-muted-foreground">最終同期</p>
                <p className="text-sm font-medium">
                  {syncData?.last_synced_at ? formatDate(syncData.last_synced_at) : '-'}
                </p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex items-center gap-3 p-4">
              {(syncData?.failed_count ?? 0) > 0 ? (
                <AlertTriangle className="h-8 w-8 text-red-500" />
              ) : (
                <CheckCircle2 className="h-8 w-8 text-muted-foreground" />
              )}
              <div>
                <p className="text-xs text-muted-foreground">エラー</p>
                <p className={`text-xl font-bold ${(syncData?.failed_count ?? 0) > 0 ? 'text-red-600' : ''}`}>
                  {syncData?.failed_count ?? '-'}
                </p>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* ── Filter Bar ── */}
        <Card>
          <CardContent className="p-4">
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="flex flex-1 gap-2">
                <Input
                  placeholder="ファイル名を検索..."
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  onKeyDown={handleKeyDown}
                  className="flex-1"
                />
                <Button variant="outline" onClick={applyFilters}>
                  <Search className="h-4 w-4" />
                </Button>
              </div>
              <Select
                value={filters.classification ?? 'all'}
                onValueChange={(v) =>
                  setFilters((prev) => ({
                    ...prev,
                    classification: v === 'all' ? undefined : v,
                    page: 1,
                  }))
                }
              >
                <SelectTrigger className="w-full sm:w-40">
                  <SelectValue placeholder="機密レベル" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">すべて</SelectItem>
                  <SelectItem value="public">公開</SelectItem>
                  <SelectItem value="internal">社内</SelectItem>
                  <SelectItem value="restricted">制限</SelectItem>
                  <SelectItem value="confidential">機密</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* ── File Table ── */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">
              {filesLoading
                ? 'ファイルを読み込み中...'
                : `${filesData?.total ?? 0}件のファイル`}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="px-4 py-3 text-left font-medium text-muted-foreground">ファイル名</th>
                    <th className="hidden px-4 py-3 text-left font-medium text-muted-foreground sm:table-cell">種類</th>
                    <th className="px-4 py-3 text-left font-medium text-muted-foreground">機密レベル</th>
                    <th className="hidden px-4 py-3 text-left font-medium text-muted-foreground md:table-cell">サイズ</th>
                    <th className="hidden px-4 py-3 text-left font-medium text-muted-foreground lg:table-cell">最終更新</th>
                    <th className="hidden px-4 py-3 text-left font-medium text-muted-foreground lg:table-cell">ステータス</th>
                    <th className="px-4 py-3 text-right font-medium text-muted-foreground">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {filesLoading &&
                    Array.from({ length: 5 }).map((_, i) => (
                      <tr key={i}>
                        <td className="px-4 py-3" colSpan={7}>
                          <Skeleton className="h-6 w-full" />
                        </td>
                      </tr>
                    ))}

                  {!filesLoading && (filesData?.files ?? []).length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-4 py-12 text-center text-muted-foreground">
                        ファイルが見つかりません
                      </td>
                    </tr>
                  )}

                  {!filesLoading &&
                    (filesData?.files ?? []).map((file) => {
                      const clf = CLASSIFICATION_CONFIG[file.classification] ?? {
                        label: file.classification,
                        className: 'bg-gray-100 text-gray-800',
                      };
                      const statusConf = STATUS_CONFIG[file.processing_status ?? ''];
                      const displayName = file.title || file.file_name || '(名前なし)';

                      return (
                        <tr key={file.id} className="hover:bg-muted/30 transition-colors">
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              {getFileIcon(file.file_type)}
                              <span className="max-w-[180px] truncate font-medium sm:max-w-[240px]">
                                {displayName}
                              </span>
                            </div>
                          </td>
                          <td className="hidden px-4 py-3 text-muted-foreground sm:table-cell">
                            {file.file_type?.toUpperCase() ?? '-'}
                          </td>
                          <td className="px-4 py-3">
                            <span
                              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${clf.className}`}
                            >
                              {clf.label}
                            </span>
                          </td>
                          <td className="hidden px-4 py-3 text-muted-foreground md:table-cell">
                            {formatFileSize(file.file_size_bytes)}
                          </td>
                          <td className="hidden px-4 py-3 text-muted-foreground lg:table-cell">
                            {formatDate(file.google_drive_last_modified ?? file.updated_at)}
                          </td>
                          <td className="hidden px-4 py-3 lg:table-cell">
                            {statusConf ? (
                              <span className="flex items-center gap-1 text-xs">
                                {statusConf.icon}
                                {statusConf.label}
                              </span>
                            ) : (
                              <span className="text-xs text-muted-foreground">
                                {file.processing_status ?? '-'}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center justify-end gap-1">
                              {isSafeUrl(file.google_drive_web_view_link) && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  asChild
                                >
                                  <a
                                    href={file.google_drive_web_view_link}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    title="Driveで開く"
                                  >
                                    <ExternalLink className="h-4 w-4" />
                                  </a>
                                </Button>
                              )}
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={downloading}
                                title="ダウンロード"
                                onClick={() =>
                                  download({
                                    documentId: file.id,
                                    fileName: file.file_name || file.title || 'download',
                                  })
                                }
                              >
                                <Download className="h-4 w-4" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {!filesLoading && (filesData?.total ?? 0) > PER_PAGE && (
              <div className="flex items-center justify-between border-t px-4 py-3">
                <p className="text-xs text-muted-foreground">
                  {currentPage} / {totalPages} ページ（全{filesData?.total}件）
                </p>
                <div className="flex gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={currentPage <= 1}
                    onClick={() =>
                      setFilters((prev) => ({ ...prev, page: (prev.page ?? 1) - 1 }))
                    }
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={currentPage >= totalPages}
                    onClick={() =>
                      setFilters((prev) => ({ ...prev, page: (prev.page ?? 1) + 1 }))
                    }
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Upload Modal */}
      {showUpload && <UploadModal onClose={() => setShowUpload(false)} />}
    </AppLayout>
  );
}
