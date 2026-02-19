/**
 * KPI Card component
 * Displays a metric with trend indicator and optional tooltip
 */

import { type LucideIcon, TrendingUp, TrendingDown } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { InfoTooltip } from '@/components/ui/info-tooltip';

interface KpiCardProps {
  title: string;
  value: number | string;
  change?: number;
  icon: LucideIcon;
  format?: 'number' | 'currency' | 'seconds' | 'ms';
  tooltip?: string;
}

function formatValue(value: number | string, format?: string): string {
  if (typeof value === 'string') return value;

  switch (format) {
    case 'currency':
      return `¥${value.toFixed(0)}`;
    case 'seconds':
      return `${value.toFixed(1)}s`;
    case 'ms':
      return `${value.toFixed(0)}ms`;
    default:
      return value.toLocaleString();
  }
}

export function KpiCard({ title, value, change, icon: Icon, format, tooltip }: KpiCardProps) {
  const isPositive = change !== undefined && change > 0;
  const isNegative = change !== undefined && change < 0;
  const TrendIcon = isPositive ? TrendingUp : TrendingDown;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">
          {title}
          {tooltip && <InfoTooltip text={tooltip} />}
        </CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{formatValue(value, format)}</div>
        {change !== undefined && (
          <div className="mt-2 flex items-center gap-2">
            <Badge
              variant={isPositive ? 'default' : isNegative ? 'destructive' : 'secondary'}
              className="gap-1"
            >
              <TrendIcon className="h-3 w-3" />
              {Math.abs(change).toFixed(1)}%
            </Badge>
            <p className="text-xs text-muted-foreground">前期間比</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
