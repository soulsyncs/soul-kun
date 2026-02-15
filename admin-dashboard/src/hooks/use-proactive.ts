/**
 * Proactive action data hooks (TanStack Query)
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useProactiveActions(params?: { trigger_type?: string }) {
  return useQuery({
    queryKey: ['proactive', 'actions', params],
    queryFn: () => api.proactive.getActions(params),
  });
}

export function useProactiveStats() {
  return useQuery({
    queryKey: ['proactive', 'stats'],
    queryFn: () => api.proactive.getStats(),
  });
}
