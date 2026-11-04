-- =============================================================================
-- ART MATE Supabase Storage 설정 (v0.4 작품 사진 + v0.5 피드백 녹음, 비공개 버킷 + RLS 정책)
--
-- 적용 대상: Supabase 프로젝트 (SQL Editor 또는 psql). 로컬·CI PostgreSQL에는 storage 스키마가 없으므로
--           적용하지 않는다.
-- 선행 조건: Alembic 0004 적용 (artmate_private 권한 함수 3개가 있어야 함)
-- 여러 번 실행해도 같은 결과가 되도록 작성했다 (idempotent).
--
-- 권한 모델
-- - 백엔드는 service_role 키 없이 "요청한 사용자의 access token"으로 Storage API를 호출한다.
-- - 아래 정책이 storage.objects 에서 다시 권한을 검사한다 (백엔드 검사가 1차, 이 정책이 2차 방어).
--   * 업로드·삭제: 사진 행(artwork_photos)의 소유자 본인, 경로 첫 폴더 = 본인 user id
--   * 읽기(Signed URL 발급): 소유자 본인, 또는 학원 연결 작품의 담당 강사·학원 관리자
-- - 버킷은 비공개(public = false). 파일은 짧은 만료의 Signed URL로만 내려받는다.
-- - 버킷 크기·형식 제한은 백엔드 설정(ARTWORK_MAX_UPLOAD_BYTES, ARTWORK_ALLOWED_CONTENT_TYPES)과 맞춘다.
-- =============================================================================

BEGIN;

-- 1) 비공개 버킷
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('artworks', 'artworks', false, 10485760, ARRAY['image/jpeg', 'image/png', 'image/webp'])
ON CONFLICT (id) DO UPDATE
SET public = false,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

-- 2) 정책에서 권한 함수를 호출할 수 있도록 authenticated 역할에만 실행 권한 부여
--    (artmate_private 스키마는 Data API에 노출하지 않는다: Settings > API > Exposed schemas에 추가 금지)
GRANT USAGE ON SCHEMA artmate_private TO authenticated;
GRANT EXECUTE ON FUNCTION artmate_private.can_access_artwork_object(uuid, text, text) TO authenticated;

-- 3) storage.objects 정책 (artworks 버킷 전용)
DROP POLICY IF EXISTS "artmate_artworks_select" ON storage.objects;
CREATE POLICY "artmate_artworks_select" ON storage.objects
    FOR SELECT TO authenticated
    USING (
        bucket_id = 'artworks'
        AND artmate_private.can_access_artwork_object(auth.uid(), name, 'read')
    );

DROP POLICY IF EXISTS "artmate_artworks_insert" ON storage.objects;
CREATE POLICY "artmate_artworks_insert" ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (
        bucket_id = 'artworks'
        AND artmate_private.can_access_artwork_object(auth.uid(), name, 'write')
    );

DROP POLICY IF EXISTS "artmate_artworks_delete" ON storage.objects;
CREATE POLICY "artmate_artworks_delete" ON storage.objects
    FOR DELETE TO authenticated
    USING (
        bucket_id = 'artworks'
        AND artmate_private.can_access_artwork_object(auth.uid(), name, 'write')
    );

-- UPDATE(덮어쓰기) 정책은 만들지 않는다: 경로가 사진마다 고유하고 교체는 새 사진으로 처리한다.

COMMIT;

-- =============================================================================
-- v0.5 피드백 녹음: 비공개 오디오 버킷 feedback-audio
--   * 업로드·삭제: 녹음 행(feedback_recordings)의 소유 학생, 경로 첫 폴더 = 본인 user id
--   * 읽기(재생 Signed URL): 소유 학생, 또는 학원 연결 작품의 담당 강사·학원 관리자
--   * 크기·형식 제한은 RECORDING_MAX_UPLOAD_BYTES, RECORDING_ALLOWED_CONTENT_TYPES 와 맞춘다
-- =============================================================================

BEGIN;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'feedback-audio', 'feedback-audio', false, 26214400,
    ARRAY['audio/webm', 'audio/ogg', 'audio/mp4', 'audio/mpeg', 'audio/wav']
)
ON CONFLICT (id) DO UPDATE
SET public = false,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

GRANT EXECUTE ON FUNCTION artmate_private.manages_student(uuid, uuid, uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION artmate_private.can_access_recording_object(uuid, text, text) TO authenticated;

DROP POLICY IF EXISTS "artmate_audio_select" ON storage.objects;
CREATE POLICY "artmate_audio_select" ON storage.objects
    FOR SELECT TO authenticated
    USING (
        bucket_id = 'feedback-audio'
        AND artmate_private.can_access_recording_object(auth.uid(), name, 'read')
    );

DROP POLICY IF EXISTS "artmate_audio_insert" ON storage.objects;
CREATE POLICY "artmate_audio_insert" ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (
        bucket_id = 'feedback-audio'
        AND artmate_private.can_access_recording_object(auth.uid(), name, 'write')
    );

DROP POLICY IF EXISTS "artmate_audio_delete" ON storage.objects;
CREATE POLICY "artmate_audio_delete" ON storage.objects
    FOR DELETE TO authenticated
    USING (
        bucket_id = 'feedback-audio'
        AND artmate_private.can_access_recording_object(auth.uid(), name, 'write')
    );

COMMIT;

-- 확인용
-- SELECT id, public, file_size_limit, allowed_mime_types FROM storage.buckets
--   WHERE id IN ('artworks', 'feedback-audio');
-- SELECT policyname, cmd FROM pg_policies WHERE schemaname = 'storage' AND tablename = 'objects'
--   AND policyname LIKE 'artmate_%';  -- artworks 3개 + audio 3개
