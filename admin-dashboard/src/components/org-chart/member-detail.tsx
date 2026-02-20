/**
 * Member detail panel for org chart
 * Shows member info and allows editing (Level 6+)
 */

import { User, Mail, Building2, Shield, X } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useMemberDetail } from '@/hooks/use-departments';
import type { DepartmentMember } from '@/types/api';

interface MemberDetailProps {
  member: DepartmentMember;
  onClose?: () => void;
}

export function MemberDetail({ member, onClose }: MemberDetailProps) {
  const { data, isLoading } = useMemberDetail(member.user_id);

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

  const detail = data;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <User className="h-4 w-4" />
            {detail?.name || member.name || '名前未設定'}
          </CardTitle>
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
      </CardContent>
    </Card>
  );
}
