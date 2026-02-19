/**
 * Hooks for system health data and emergency stop
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useSystemHealth() {
  return useQuery({
    queryKey: ['system', 'health'],
    queryFn: () => api.system.getHealth(),
  });
}

export function useSystemMetrics(days?: number) {
  return useQuery({
    queryKey: ['system', 'metrics', days],
    queryFn: () => api.system.getMetrics({ days }),
  });
}

export function useSelfDiagnoses() {
  return useQuery({
    queryKey: ['system', 'diagnoses'],
    queryFn: () => api.system.getDiagnoses(),
  });
}

export function useEmergencyStopStatus() {
  return useQuery({
    queryKey: ['emergency-stop', 'status'],
    queryFn: () => api.emergencyStop.getStatus(),
    refetchInterval: 10_000, // 10秒ごとに自動更新
  });
}

export function useActivateEmergencyStop() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (reason: string) => api.emergencyStop.activate(reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['emergency-stop'] });
    },
  });
}

export function useDeactivateEmergencyStop() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.emergencyStop.deactivate(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['emergency-stop'] });
    },
  });
}
