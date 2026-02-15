/**
 * Hooks for system health data
 */

import { useQuery } from '@tanstack/react-query';
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
