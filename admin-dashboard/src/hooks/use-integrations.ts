/**
 * 連携設定フック
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useGoogleCalendarStatus() {
  return useQuery({
    queryKey: ['integrations', 'google-calendar', 'status'],
    queryFn: () => api.integrations.getGoogleCalendarStatus(),
  });
}

export function useGoogleCalendarConnect() {
  return useMutation({
    mutationFn: async () => {
      const data = await api.integrations.getGoogleCalendarConnectUrl();
      // OAuth認可画面にリダイレクト
      window.location.href = data.auth_url;
      return data;
    },
  });
}

export function useGoogleCalendarDisconnect() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.integrations.disconnectGoogleCalendar(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations', 'google-calendar'] });
    },
  });
}

export function useCalendarEvents(days: number = 14) {
  return useQuery({
    queryKey: ['integrations', 'google-calendar', 'events', days],
    queryFn: () => api.integrations.getCalendarEvents(days),
    staleTime: 5 * 60 * 1000, // 5分キャッシュ
  });
}
