# brain-reviewer Agent Memory

## Scope: admin-dashboard (frontend only)
This reviewer covers `admin-dashboard/src/` — React/TypeScript/Tailwind.
Backend lib/brain/ rules (organization_id, RLS, audit logs) do NOT apply here
because admin-dashboard is a read-only management UI (CLAUDE.md §1-1 exception).
Only the following CLAUDE.md rules directly apply to this scope:
- §3-2 checklist items: 1 (logic bugs), 2 (XSS/security), 4 (test coverage), 8 (PII in errors), 16 (hardcoded values)
- Brain bypass rule does NOT apply (§1-1 exemption)
- organization_id / RLS / audit log rules do NOT apply (frontend only)

## Recurring patterns found in admin-dashboard

### TypeScript type safety
- `TaskOverviewStats.chatwork_tasks` is NON-OPTIONAL in api.ts (line 405) but the
  component authors treated it as optional (taskStats?.chatwork_tasks?.overdue).
  This is actually CORRECT defensively because `taskStats` itself can be undefined
  while the query is loading. The inner optional chain is technically redundant per
  the type definition but harmless. Do NOT flag as a bug.
- `AiRoiResponse.roi_multiplier` is typed as `number` (non-optional). The `?? 0`
  fallback in costs.tsx (line 434) is redundant but harmless.

### Mobile responsive gaps (known issue as of 2026-02-20 review)
- goals.tsx line 260: `flex gap-6` + `w-80 shrink-0` detail panel — NOT made
  responsive. On mobile, the 320px fixed-width side panel will overflow on small
  screens. This was NOT fixed in this PR despite members.tsx being fixed.
- costs.tsx line 418: `grid grid-cols-3` ROI card — no md: breakpoint. Three
  columns will be cramped at 390px. Minor but worth flagging.

### Navigation: raw <a href> vs <Link> inconsistency
- dashboard.tsx line 288 uses raw `<a href="/tasks">` instead of TanStack Router
  `<Link to="/tasks">`. This causes a full page reload and breaks SPA navigation.
  All other pages use `<Link>` from @tanstack/react-router correctly.

### Accessibility gaps
- app-layout.tsx hamburger button: missing `aria-expanded={sidebarOpen}` and
  `aria-controls` attribute referencing the sidebar element.
- sidebar.tsx: nav element missing `aria-label` (e.g., aria-label="メインナビゲーション").

### z-index stacking in app-layout
- Overlay: z-20, Sidebar: z-30 — correct order.
- `md:z-auto` on sidebar wrapper resets z-index on desktop — correct.

## Backend API pattern (admin routes)
- `deps.py` exports: `require_admin` (Level 5+), `require_editor` (Level 6+), `DEFAULT_ORG_ID`
- Read-only GET endpoints use `require_admin`; other admin write endpoints (departments, members) use `require_editor`
- Zoom routes use `require_admin` for ALL verbs (GET/POST/PUT/DELETE) — intentional design, but inconsistent with other write endpoints
- Dynamic UPDATE SET clauses built with f-string + list of hardcoded column strings: values still bound via :params, so SQLi risk is zero, but flag pattern in future reviews (WARNING-level, not CRITICAL)
- `organization_id = user.organization_id or DEFAULT_ORG_ID` pattern is standard in this codebase — acceptable

## Zoom webhook: org_id NOT in secret lookup query (intentional, documented)
- `_get_webhook_secret_for_account` in chatwork-webhook/routes/zoom.py queries
  zoom_accounts by zoom_account_id only (no org_id filter). This is correct because:
  (a) zoom_account_id values are globally unique per Zoom account and are not secret,
  (b) only webhook_secret_token (not any org-specific data) is returned,
  (c) the returned token is used immediately to verify the Zoom HMAC signature,
      so a cross-org secret lookup would only cause signature failure (self-correcting),
  (d) the webhook endpoint has no user session context to filter by org_id anyway.
  Do NOT flag this as missing org_id — it is architecturally sound.

## Zoom webhook: security concern — JSON parse before signature verification
- In chatwork-webhook/routes/zoom.py, JSON is parsed BEFORE signature verification in
  order to read account_id and choose the correct secret. This is a known trade-off:
  attacker can send arbitrary JSON to trigger a DB read (at no auth cost), but:
  (a) the DB read only returns a secret token, nothing sensitive is exposed,
  (b) signature verification still happens before any business logic,
  (c) the index on zoom_account_id WHERE is_active=true makes the lookup cheap.
  Flag as WARNING (denial-of-service amplification risk from unauthenticated DB hit)
  but not CRITICAL. Mitigate with rate limiting at infrastructure level.

## Zoom accounts: secret storage pattern
- webhook_secret_token stored as plaintext TEXT in DB. This is NOT encrypted at rest
  at application level. Acceptable because Cloud SQL has disk encryption, but
  should be flagged as WARNING for future migration to Secret Manager per-account
  (same pattern as zoom-webhook-secret-token in Secret Manager today).

## ZoomAccountUpdate: default_room_id cannot be cleared to NULL
- In zoom_routes.py update_zoom_account, `if body.default_room_id is not None`
  means sending `default_room_id: ""` (empty string) will try to set it to "",
  but sending `null` in JSON will skip the clause entirely (cannot clear to NULL).
  This is a design gap — no way to remove a default room once set.
  Flag as WARNING (feature gap, not security issue).

## Files reviewed on 2026-02-20
- src/components/layout/app-layout.tsx
- src/components/layout/sidebar.tsx
- src/pages/morning-briefing.tsx
- src/pages/dashboard.tsx
- src/pages/costs.tsx
- src/pages/members.tsx
- src/pages/goals.tsx

## Files reviewed on 2026-02-20 (Phase Z1 Zoom review)
- migrations/20260220_zoom_meeting_configs.sql
- migrations/20260220_zoom_meeting_configs_rollback.sql
- api/app/api/v1/admin/zoom_routes.py
- api/app/api/v1/admin/__init__.py
- api/app/api/v1/admin/deps.py
- admin-dashboard/src/pages/zoom-settings.tsx
- admin-dashboard/src/App.tsx
- admin-dashboard/src/components/layout/sidebar.tsx
- admin-dashboard/src/lib/api.ts (zoomSettings section)

## Files reviewed on 2026-02-20 (Phase Z2 ③ Zoom multiple accounts review)
- migrations/20260220_zoom_accounts.sql
- migrations/20260220_zoom_accounts_rollback.sql
- api/app/api/v1/admin/zoom_routes.py (zoomAccounts section appended)
- chatwork-webhook/routes/zoom.py (full rewrite with multi-account support)
- admin-dashboard/src/pages/zoom-settings.tsx (full rewrite with tabs)
- admin-dashboard/src/lib/api.ts (zoomAccounts section)

## Files reviewed on 2026-02-21 (Members CRUD review)
- api/app/api/v1/admin/members_routes.py (POST/PUT/DELETE追加)
- admin-dashboard/src/pages/members.tsx (AddDialog/EditDialog/DeleteDialog追加)

### Members CRUD: 修正確認済み (2026-02-21 再レビューでPASS)
- C-1 修正済み: 行546-548の `x or ""` パターン除去済み。`body.email`/`body.chatwork_account_id`/`body.role` をそのまま渡す
- C-2 解決済み: POST/PUT=require_admin(Level5+)、DELETE=require_editor(Level6+) は意図的設計。
  description に「削除は誤操作防止のため Level 6 のみ」と明記済み。設計として合理的（PASS）
- W-3 修正済み: PUT の chatwork_account_id 重複チェック追加済み(行636-656)。org_id+自己除外フィルタ正しい

### Members CRUD: known design gaps (残存 WARNING — 将来対応)
- UpdateMemberRequest のフィールド (employment_type/avatar_url/evaluation/skills等8件) が
  PUT /members/{user_id} の実装で完全に無視されている。スキーマと実装が乖離。
- audit_log details に uid/org_id キー名が混入 (行669-670でdict追加後に list(updates.keys()) を呼ぶ)。
  値ではないのでPIIリスクゼロだが冗長。SUGGESTION レベル。
- members.tsx の削除ボタンは Level5 ユーザーにも表示 → API 403 でユーザーが混乱する。

### members.tsx: CRUD UX patterns (confirmed safe)
- useMutation + useQueryClient.invalidateQueries(['members']) — 正しいパターン
- mutationError は3ダイアログで共有 (共通stateだが onOpenChange でリセット済み)
- editForm に selectedUserId が null の場合の guard: `selectedUserId && editMutation.mutate(...)` — 安全

## Files reviewed on 2026-02-21 (Phase 3-B Teachings CRUD review)
- api/app/schemas/admin.py (CreateTeachingRequest 追加)
- api/app/api/v1/admin/teachings_routes.py (POST /teachings 追加)
- admin-dashboard/src/pages/teachings.tsx (AddDialog追加)

### Teachings CRUD: FAIL — C-1・W-2 修正必須

**C-1 (CRITICAL): DepartmentMutationResponse フィールドミスマッチ**
- teachings_routes.py 行406-410: `DepartmentMutationResponse(id=new_id, ...)` が誤り
- `DepartmentMutationResponse` の必須フィールドは `department_id`（not `id`）
- INSERT 成功後に Pydantic ValidationError → 500 返却。ユーザー再送で重複 INSERT 発生
- 修正案A: `department_id=new_id` に変更（フィールド名流用）
- 修正案B: `CreateTeachingResponse(teaching_id=new_id, ...)` 専用クラス作成（推奨）

**W-1 (WARNING): POST の organization_id に or DEFAULT_ORG_ID がない**
- teachings_routes.py 行367: `organization_id = user.organization_id`（フォールバックなし）
- 他の全 GET エンドポイントは `user.organization_id or DEFAULT_ORG_ID` — 不整合

**W-2 (WARNING): category が DB CHECK 制約と不整合**
- phase2d_ceo_learning.sql 行97-109: `chk_ceo_teachings_category` で13種の英語値のみ許可
  （mvv_mission, mvv_values, choice_theory, sdt, servant, psych_safety,
   biz_sales, biz_hr, biz_accounting, biz_general, culture, communication, staff_guidance, other）
- CreateTeachingRequest.category は自由記述（max_length=100 のみ）
- UI プレースホルダーが「組織文化、営業戦略」等の日本語を示しており全入力が CHECK 違反
- 修正: Literal 型バリデーション追加 OR DB CHECK 制約を削除して自由カテゴリを許可

### ceo_teachings テーブルの型情報（確認済み）
- organization_id: UUID NOT NULL → INSERT の CAST(:org_id AS uuid) は正しい
- RLS ポリシー: `::uuid` キャスト（20260208_rls_expansion.sql）— UUID 型と一致、OK
- category: VARCHAR(50) + CHECK 制約（13種の英語値のみ）
- subcategory: VARCHAR(50)（任意）
- ceo_user_id: UUID — 管理者 user_id を渡すのは現在のシングルテナントでは許容

### DepartmentMutationResponse 流用パターン（注意）
- members, departments, teachings の POST/PUT/DELETE で DepartmentMutationResponse を流用
- フィールドは `status`, `department_id`（必須）, `message` の3つ
- teachings で `id=new_id` と書くと CRITICAL バグ（department_id が必須なのに未指定）
- 将来の各エンドポイント専用レスポンス型作成を推奨
