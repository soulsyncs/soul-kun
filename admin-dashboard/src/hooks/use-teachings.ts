/**
 * Hooks for CEO teachings data
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useTeachingsList(params?: { category?: string; is_active?: boolean }) {
  return useQuery({
    queryKey: ['teachings', 'list', params],
    queryFn: () => api.teachings.getList(params),
  });
}

export function useTeachingConflicts() {
  return useQuery({
    queryKey: ['teachings', 'conflicts'],
    queryFn: () => api.teachings.getConflicts(),
  });
}

export function useTeachingUsageStats() {
  return useQuery({
    queryKey: ['teachings', 'usage-stats'],
    queryFn: () => api.teachings.getUsageStats(),
  });
}
