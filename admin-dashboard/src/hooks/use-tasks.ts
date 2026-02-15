/**
 * Tasks data hooks (TanStack Query)
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useTasksOverview() {
  return useQuery({
    queryKey: ['tasks', 'overview'],
    queryFn: () => api.tasks.getOverview(),
  });
}

export function useTasksList(params?: { source?: string }) {
  return useQuery({
    queryKey: ['tasks', 'list', params],
    queryFn: () => api.tasks.getList(params),
  });
}
