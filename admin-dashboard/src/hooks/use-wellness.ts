/**
 * Wellness / Emotion data hooks (TanStack Query)
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useEmotionAlerts(params?: {
  risk_level?: string;
  status?: string;
}) {
  return useQuery({
    queryKey: ['wellness', 'alerts', params],
    queryFn: () => api.wellness.getAlerts(params),
  });
}

export function useEmotionTrends(params?: {
  days?: number;
  department_id?: string;
}) {
  return useQuery({
    queryKey: ['wellness', 'trends', params],
    queryFn: () => api.wellness.getTrends(params),
  });
}
