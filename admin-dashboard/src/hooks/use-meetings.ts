/**
 * Meetings data hooks (TanStack Query)
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useMeetingsList(params?: { status?: string }) {
  return useQuery({
    queryKey: ['meetings', 'list', params],
    queryFn: () => api.meetings.getList(params),
  });
}
