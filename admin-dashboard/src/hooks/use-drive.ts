/**
 * Google Drive管理フック
 *
 * ファイル一覧・同期状態・アップロードのReact Queryフック。
 */

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface DriveFilters {
  q?: string;
  classification?: string;
  department_id?: string;
  page?: number;
  per_page?: number;
}

export function useDriveFiles(filters: DriveFilters = {}) {
  return useQuery({
    queryKey: ['drive', 'files', filters],
    queryFn: () => api.drive.getFiles(filters),
    staleTime: 5 * 60 * 1000, // 5分キャッシュ
  });
}

export function useDriveSyncStatus() {
  return useQuery({
    queryKey: ['drive', 'sync-status'],
    queryFn: () => api.drive.getSyncStatus(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useDownloadDriveFile() {
  return useMutation({
    mutationFn: ({ documentId, fileName }: { documentId: string; fileName: string }) =>
      api.drive.downloadFile(documentId, fileName),
  });
}

export function useUploadDriveFile() {
  const queryClient = useQueryClient();
  const [uploadProgress, setUploadProgress] = useState(0);

  const mutation = useMutation({
    mutationFn: ({ file, classification }: { file: File; classification: string }) =>
      api.drive.uploadFile(file, classification, (pct) => setUploadProgress(pct)),
    onSuccess: () => {
      setUploadProgress(0);
      queryClient.invalidateQueries({ queryKey: ['drive'] });
    },
    onError: () => {
      setUploadProgress(0);
    },
  });

  return { ...mutation, uploadProgress };
}
