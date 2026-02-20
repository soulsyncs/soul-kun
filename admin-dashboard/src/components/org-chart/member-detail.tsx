/**
 * Member detail panel for org chart
 * Shows member info and allows editing (Level 6+)
 */

import { useState, useEffect } from 'react';
import { User, Mail, Building2, Shield, X, Calendar, Clock, Pencil, Briefcase } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { useMemberDetail, useUpdateMember } from '@/hooks/use-departments';
import type { DepartmentMember } from '@/types/api';

const formatDate = (iso: string | null): string | null =>
  iso ? new Date(iso).toLocaleDateString('ja-JP', { year: 'numeric', month: 'long', day: 'numeric' }) : null;

interface MemberDetailProps {
  member: DepartmentMember;
  onClose?: () => void;
}

export function MemberDetail({ member, onClose }: MemberDetailProps) {
  const { data, isLoading } = useMemberDetail(member.user_id);
  const updateMember = useUpdateMember();

  const [isEditOpen, setIsEditOpen] = useState(false);
  const [formName, setFormName] = useState('');
  const [formEmail, setFormEmail] = useState('');
  const [formChatworkId, setFormChatworkId] = useState('');
  const [formEmploymentType, setFormEmploymentType] = useState('');
  const [formAvatarUrl, setFormAvatarUrl] = useState('');

  const detail = data;

  // フォームを開くたびに最新データで初期化
  useEffect(() => {
    if (isEditOpen && detail) {
      setFormName(detail.name ?? '');
      setFormEmail(detail.email ?? '');
      setFormChatworkId(detail.chatwork_account_id ?? '');
      setFormEmploymentType(detail.employment_type ?? '');
      setFormAvatarUrl(detail.avatar_url ?? '');
    }
  }, [isEditOpen, detail]);

  const handleSave = async () => {
    if (!formName.trim()) return;
    try {
      await updateMember.mutateAsync({
        userId: member.user_id,
        data: {
          name: formName.trim(),
          email: formEmail.trim() || undefined,
          chatwork_account_id: formChatworkId.trim() || undefined,
          employment_type: formEmploymentType.trim() || undefined,
          avatar_url: formAvatarUrl.trim() || undefined,
        },
      });
      setIsEditOpen(false);
    } catch {
      alert('保存に失敗しました。もう一度お試しください。');
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className="p-4 space-y-3">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-4 w-24" />
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              {detail?.avatar_url ? (
                <img
                  src={detail.avatar_url}
                  alt={detail.name ?? ''}
                  className="h-8 w-8 rounded-full object-cover border border-border"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
              ) : (
                <User className="h-4 w-4" />
              )}
              {detail?.name || member.name || '名前未設定'}
            </CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 w-7 p-0"
                onClick={() => setIsEditOpen(true)}
                aria-label="編集"
              >
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              {onClose && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0"
                  onClick={onClose}
                  aria-label="閉じる"
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {detail?.email && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Mail className="h-3.5 w-3.5" />
              {detail.email}
            </div>
          )}

          {detail?.role && (
            <div className="flex items-center gap-2 text-sm">
              <Shield className="h-3.5 w-3.5 text-muted-foreground" />
              <Badge variant="secondary">{detail.role}</Badge>
              {detail.role_level != null && (
                <span className="text-xs text-muted-foreground">
                  (Level {detail.role_level})
                </span>
              )}
            </div>
          )}

          {detail?.departments && detail.departments.length > 0 && (
            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground">所属部署</div>
              {detail.departments.map((dept) => (
                <div
                  key={dept.department_id}
                  className="flex items-center gap-2 text-sm"
                >
                  <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
                  <span>{dept.department_name}</span>
                  {dept.is_primary && (
                    <Badge variant="outline" className="text-xs">
                      主所属
                    </Badge>
                  )}
                </div>
              ))}
            </div>
          )}

          {detail?.chatwork_account_id && (
            <div className="text-xs text-muted-foreground">
              ChatWork ID: {detail.chatwork_account_id}
            </div>
          )}

          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant={detail?.is_active !== false ? 'default' : 'secondary'}>
              {detail?.is_active !== false ? '在籍中' : '非アクティブ'}
            </Badge>
            {detail?.employment_type && (
              <Badge variant="outline" className="text-xs">
                {detail.employment_type}
              </Badge>
            )}
          </div>

          {formatDate(detail?.hire_date ?? null) && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Briefcase className="h-3 w-3" />
              入社日: {formatDate(detail?.hire_date ?? null)}
            </div>
          )}

          {formatDate(detail?.created_at ?? null) && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Calendar className="h-3 w-3" />
              登録日: {formatDate(detail?.created_at ?? null)}
            </div>
          )}

          {formatDate(detail?.updated_at ?? null) && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Clock className="h-3 w-3" />
              最終更新: {formatDate(detail?.updated_at ?? null)}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 編集ダイアログ */}
      <Dialog open={isEditOpen} onOpenChange={setIsEditOpen}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle>メンバー情報を編集</DialogTitle>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="member-name">お名前 *</Label>
              <Input
                id="member-name"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="例: 田中 太郎"
                maxLength={100}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="member-email">メールアドレス</Label>
              <Input
                id="member-email"
                type="email"
                value={formEmail}
                onChange={(e) => setFormEmail(e.target.value)}
                placeholder="例: taro@soulsyncs.jp"
                maxLength={200}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="member-chatwork">ChatWork ID</Label>
              <Input
                id="member-chatwork"
                value={formChatworkId}
                onChange={(e) => setFormChatworkId(e.target.value)}
                placeholder="例: 1728974"
                maxLength={50}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="member-employment-type">雇用形態</Label>
              <select
                id="member-employment-type"
                value={formEmploymentType}
                onChange={(e) => setFormEmploymentType(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="">未設定</option>
                <option value="正社員">正社員</option>
                <option value="業務委託">業務委託</option>
                <option value="パート">パート</option>
                <option value="インターン">インターン</option>
                <option value="顧問">顧問</option>
              </select>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="member-avatar-url">顔写真URL</Label>
              <Input
                id="member-avatar-url"
                value={formAvatarUrl}
                onChange={(e) => setFormAvatarUrl(e.target.value)}
                placeholder="https://example.com/photo.jpg"
                maxLength={500}
              />
              {formAvatarUrl && (
                <img
                  src={formAvatarUrl}
                  alt="プレビュー"
                  className="h-12 w-12 rounded-full object-cover border border-border"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
              )}
            </div>
          </div>

          <DialogFooter className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => setIsEditOpen(false)}
              disabled={updateMember.isPending}
            >
              キャンセル
            </Button>
            <Button
              onClick={handleSave}
              disabled={updateMember.isPending || !formName.trim()}
            >
              {updateMember.isPending ? '保存中...' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
