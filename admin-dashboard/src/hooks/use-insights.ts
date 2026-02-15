/**
 * Insights data hooks (TanStack Query)
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useInsightsList(params?: {
  importance?: string;
  status?: string;
}) {
  return useQuery({
    queryKey: ['insights', 'list', params],
    queryFn: () => api.insights.getList(params),
  });
}

export function useQuestionPatterns() {
  return useQuery({
    queryKey: ['insights', 'patterns'],
    queryFn: () => api.insights.getPatterns(),
  });
}

export function useWeeklyReports() {
  return useQuery({
    queryKey: ['insights', 'weekly-reports'],
    queryFn: () => api.insights.getWeeklyReports(),
  });
}
