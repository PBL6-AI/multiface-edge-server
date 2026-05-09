# Phân tích luồng pipeline video -> AI -> điểm danh trong `multiface-attendace-for-classroom`

## Kết luận ngắn

Repo này hiện có **2 nhánh xử lý video song song**:

1. `POST /api/video/process/`: xử lý video trực tiếp trong Django bằng `VideoProcessor`.
2. `POST /api/video/run/`: gọi một script ngoài workspace là `Attendance_Workspace/scripts/import_group_video_to_tracks.py`.

Điểm quan trọng:

- Nhánh `POST /api/recognize/` là luồng **ghi attendance record đầy đủ** cho ảnh đơn lẻ.
- Hai nhánh video hiện tại chủ yếu là **phân tích / test / preview kết quả nhận diện theo frame hoặc track**, chưa thấy đoạn code nào trong repo này ghi `AttendanceRecord` cho từng track video như nhánh ảnh đơn lẻ.
- Nhánh `POST /api/video/run/` còn phụ thuộc vào một script ngoài repo. Trong workspace hiện tại, script đó **không tồn tại**, nên đây là một dependency ngoài cần lưu ý.

---

## 1. Các entrypoint chính

Mapping URL nằm tại `core_app/urls.py`:

- `api/gallery/build/` -> build gallery embeddings từ dataset: `core_app/urls.py:12`
- `api/recognize/` -> nhận diện ảnh đơn và ghi nhận attendance: `core_app/urls.py:13`
- `api/video/process/` -> upload video, xử lý trong Django: `core_app/urls.py:18`
- `api/video/run/` -> chạy pipeline video qua script ngoài: `core_app/urls.py:19`

Nguồn:

- `core_app/urls.py:4-20`

---

## 2. Thành phần AI cốt lõi

### 2.1. Face detection + alignment

File `core_app/utils.py` khởi tạo `InsightFace FaceAnalysis` với module detection:

- model detector: `buffalo_sc`
- provider: `CPUExecutionProvider`
- kích thước detect: `640 x 640`

Luồng xử lý:

1. `process_base64_image()` giải mã base64 thành ảnh OpenCV BGR.
2. `detect_and_align_face()` gọi `app.get(image_cv)` để detect face.
3. Chọn face có `det_score` cao nhất.
4. Nếu `det_score < 0.8` thì fail.
5. Căn chỉnh về chuẩn `112 x 112` bằng `SimilarityTransform`.

Nguồn:

- `core_app/utils.py:18-19`
- `core_app/utils.py:33-42`
- `core_app/utils.py:44-62`

### 2.2. Embedding extractor và model recognition

File `core_app/face_recognition_engine.py` là lõi AI:

1. Nạp checkpoint PyTorch bằng `torch.load`.
2. Dựng model qua `build_model_from_metadata`.
3. Chuẩn hóa ảnh aligned face:
   - resize về `112 x 112`
   - BGR -> RGB
   - scale về `[0,1]`
   - normalize quanh `0.5`
4. Forward qua model để lấy embedding.
5. Chuẩn hóa embedding về vector đơn vị.

Nguồn:

- `core_app/face_recognition_engine.py:51-78`
- `core_app/face_recognition_engine.py:80-103`

### 2.3. Matching với gallery

`AttendanceRecognitionPipeline` giữ:

- `extractor`
- `gallery_embeddings`
- `similarity_threshold` mặc định `0.5`

Khi nhận diện:

1. Extract embedding từ ảnh query.
2. Tính cosine similarity với toàn bộ gallery.
3. Sắp xếp giảm dần.
4. Chọn top-1.
5. Nếu similarity >= threshold thì `recognized = True`.

Nguồn:

- `core_app/face_recognition_engine.py:187-204`
- `core_app/face_recognition_engine.py:216-272`

---

## 3. Luồng build gallery trước khi điểm danh

Trước khi chạy nhận diện, repo bắt buộc phải build gallery qua `POST /api/gallery/build/`.

### 3.1. Dữ liệu gallery lấy từ đâu

`build_gallery_from_dataset()`:

1. Nhận `checkpoint_path`, `device`, `gallery_dir`.
2. Tạo global `_pipeline_instance = AttendanceRecognitionPipeline(...)`.
3. Ưu tiên load ảnh từ thư mục gallery.
4. Nếu thư mục không có dữ liệu thì fallback sang DB `FaceImage`.

Nguồn:

- `core_app/views.py:245-304`
- `core_app/views.py:41-111`

### 3.2. Gallery embedding được tạo như thế nào

`build_gallery_embeddings_from_students()`:

1. Với mỗi `student_id`, duyệt toàn bộ ảnh.
2. Mỗi ảnh được đưa qua `extract_embedding_from_aligned_face()`.
3. Lấy trung bình embedding của các ảnh hợp lệ.
4. Normalize lại vector trung bình.
5. Lưu vào `self.gallery_embeddings[student_id]`.

Lưu ý: hàm này giả định ảnh đầu vào đã là face tương đối chuẩn/aligned. Trong repo này, ảnh dataset được kỳ vọng đã được chuẩn hóa từ trước hoặc đến từ luồng `collect_face`.

Nguồn:

- `core_app/face_recognition_engine.py:274-302`
- `core_app/views.py:135-186`

---

## 4. Luồng điểm danh chuẩn đang ghi DB: ảnh đơn `POST /api/recognize/`

Đây là luồng attendance hoàn chỉnh nhất trong repo.

### 4.1. Pipeline xử lý

1. Frontend gửi `session_id` và `image` dạng base64.
2. API kiểm tra `_pipeline_instance` đã được build chưa.
3. Decode base64 thành OpenCV image.
4. Gọi `_pipeline_instance.recognize_face(image_cv)`.
5. Lưu ảnh query tạm vào `media/temp_recognition/`.
6. Suy ra `status = MATCHED | UNMATCHED | ERROR`.
7. Nếu match thì map `student_id` sang `Student`.
8. Ghi một `AttendanceRecord`.
9. Cập nhật counter trong `AttendanceSession`.
10. Trả về JSON gồm student, confidence, top matches, timing.

Nguồn:

- `core_app/views.py:307-414`

### 4.2. Các cột DB được ghi

`AttendanceRecord` lưu:

- `session`
- `student`
- `captured_image_path`
- `recognized_student_id`
- `similarity_score`
- `confidence`
- `status`
- thời gian detection / alignment / extraction / similarity / total

Nguồn:

- `core_app/models.py:53-86`
- `core_app/views.py:366-382`

### 4.3. Ý nghĩa đối với câu hỏi “đẩy qua AI để điểm danh”

Nếu hiểu “đẩy qua AI” là:

- nhận ảnh đầu vào,
- detect + align face,
- extract embedding bằng model,
- so khớp với gallery,
- rồi ghi attendance,

thì **nhánh ảnh đơn `POST /api/recognize/` mới là luồng điểm danh hoàn chỉnh**.

---

## 5. Luồng video nội bộ `POST /api/video/process/`

Đây là nhánh video upload trực tiếp lên Django rồi xử lý trong repo.

### 5.1. Entry flow

`process_video_tracklet()` nhận:

- `session_id`
- file `video` multipart upload

Luồng:

1. Kiểm tra `_pipeline_instance` đã có chưa.
2. Ghi video upload vào file tạm `.mov`.
3. Tạo `VideoProcessor(recognition_pipeline=_pipeline_instance, face_extractor=_pipeline_instance.extractor)`.
4. Gọi `processor.process_video(temp_video_path)`.
5. Tính summary theo frame.
6. Trả JSON cho frontend.
7. Xóa file video tạm.

Nguồn:

- `core_app/views.py:701-765`

### 5.2. VideoProcessor làm gì với từng frame

`VideoProcessor.process_video()`:

1. Mở video bằng `cv2.VideoCapture`.
2. Đọc lần lượt từng frame.
3. Nếu thỏa `frame_idx % frame_skip == 0` thì mới chạy AI.
4. Gọi `_detect_and_recognize_frame(frame)`.
5. Gọi tracker để gán `track_id`.
6. Vẽ bbox + label lên frame.
7. Resize frame nếu cần rồi encode base64 để frontend preview.
8. Tích lũy `frame_results`.

Nguồn:

- `core_app/video_processor.py:183-296`

### 5.3. AI recognition trên từng frame

`_detect_and_recognize_frame(frame)`:

1. Dùng `app.get(frame)` để detect tất cả khuôn mặt trong frame.
2. Loại face có `det_score < 0.6`.
3. Với từng face:
   - cắt bbox
   - align bằng landmark
   - extract embedding
   - so cosine similarity với toàn bộ `pipeline.gallery_embeddings`
4. Nếu similarity >= `pipeline.similarity_threshold` thì gán `student_id`, ngược lại gán `Unknown`.

Nguồn:

- `core_app/video_processor.py:298-355`

### 5.4. Tracking qua nhiều frame

`FaceTracker.update()` ghép detection mới với track cũ bằng:

- `0.6 * IOU + 0.4 * embedding_similarity`

Nếu score vượt `iou_threshold` thì coi là cùng track. Track cũ bị loại sau hơn 30 frame không được update.

Nguồn:

- `core_app/video_processor.py:15-165`

### 5.5. Điểm rất quan trọng: nhánh này chưa ghi attendance record

Trong `process_video_tracklet()`:

- có xử lý video,
- có detect / recognize / track,
- có trả summary và danh sách frame,

nhưng **không có đoạn `AttendanceRecord.objects.create(...)`** như nhánh `POST /api/recognize/`.

Nói cách khác, nhánh này hiện là:

- pipeline AI cho video
- phục vụ test/demo/preview
- chưa phải luồng attendance persistence hoàn chỉnh

---

## 6. Luồng video ngoài repo `POST /api/video/run/`

Đây là nhánh video thứ hai và có vẻ được thiết kế cho pipeline “group video -> tracks -> manifest”.

### 6.1. Cách endpoint hoạt động

`run_video_track_test()`:

1. Nhận JSON gồm:
   - `video_path`
   - `checkpoint_path`
   - `gallery_dir`
   - `device`
   - các threshold/tracking params
2. Kiểm tra tồn tại của video, checkpoint, gallery dir và script recognition.
3. Dựng lệnh subprocess gọi:
   - `python import_group_video_to_tracks.py ...`
4. Chạy script trong `ATTENDANCE_WORKSPACE`.
5. Sau khi xong, đọc:
   - `group_tracks/<video_stem>/manifest.json`
   - `group_tracks/<video_stem>/summary.txt`
6. Trả về manifest + preview URLs.

Nguồn:

- `core_app/views.py:557-655`

### 6.2. Bản chất của nhánh này

Nhánh này **không triển khai AI pipeline chi tiết ngay trong repo Django**. Repo chỉ:

- validate input,
- gọi subprocess,
- đọc output artifacts,
- trả kết quả về frontend.

Toàn bộ logic AI chính của nhánh này nằm ở script ngoài:

- `Attendance_Workspace/scripts/import_group_video_to_tracks.py`

### 6.3. Trạng thái trong workspace hiện tại

Trong workspace `D:\H-Coding\PBL5`, mình kiểm tra thấy:

- không có `Attendance_Workspace/scripts/import_group_video_to_tracks.py`
- không có `Attendance_Workspace/3_edgeface_training`

Vì vậy, ở môi trường hiện tại:

- endpoint `POST /api/video/run/` có định nghĩa trong code,
- nhưng dependency để chạy thật **không nằm trong repo đang kiểm tra**.

Điều này nghĩa là muốn hiểu trọn vẹn nhánh này thì cần đọc thêm code của `Attendance_Workspace`, hiện chưa có trong source hiện tại.

---

## 7. Luồng dữ liệu end-to-end nên hiểu như thế nào

### 7.1. Luồng attendance hoàn chỉnh đang có

```text
Frontend -> /api/gallery/build
         -> tạo _pipeline_instance + build gallery embeddings

Frontend -> /api/recognize
         -> base64 image
         -> detect + align face
         -> extract embedding bằng EdgeFace
         -> cosine similarity với gallery
         -> quyết định MATCHED/UNMATCHED/ERROR
         -> ghi AttendanceRecord + update AttendanceSession
```

### 7.2. Luồng video nội bộ trong repo

```text
Frontend -> /api/video/process
         -> upload video
         -> đọc từng frame bằng OpenCV
         -> detect multi-face trên frame
         -> align + embedding + matching
         -> tracking bằng IOU + embedding similarity
         -> trả JSON frame results + preview
         -> không ghi AttendanceRecord
```

### 7.3. Luồng video external pipeline

```text
Frontend -> /api/video/run
         -> validate path/params
         -> subprocess gọi script ngoài repo
         -> script sinh manifest/summary/tracks
         -> Django đọc artifacts và trả về
         -> logic AI thực tế nằm ngoài repo này
```

---

## 8. Các model dữ liệu liên quan đến điểm danh

### 8.1. Dữ liệu nguồn

- `Student`: thông tin sinh viên
- `FaceImage`: ảnh đã thu thập của sinh viên

Nguồn:

- `core_app/models.py:5-31`

### 8.2. Dữ liệu attendance

- `AttendanceSession`: phiên điểm danh
- `AttendanceRecord`: từng lần nhận diện
- `PipelineMetrics`: thống kê tổng hợp theo session

Nguồn:

- `core_app/models.py:34-118`

---

## 9. Những nhận định kỹ thuật quan trọng

### 9.1. Repo này chưa có “video attendance commit” hoàn chỉnh

Nhận diện video đã có, tracking đã có, nhưng phần:

- tổng hợp track thành một kết quả attendance cuối cùng cho mỗi sinh viên,
- chống trùng lặp theo track / theo thời gian,
- ghi DB attendance từ video,

chưa xuất hiện trong code nội bộ của repo Django này.

### 9.2. `process_video_tracklet()` là nhánh demo/test mạnh hơn là production attendance

Dấu hiệu:

- trả `frames` chi tiết cho frontend
- encode frame preview base64
- tính summary trực tiếp từ detections
- không ghi DB

### 9.3. `run_video_track_test()` là một adapter tới hệ ngoài

Endpoint này đóng vai trò “bridge”:

- Django không xử lý AI trực tiếp ở đây
- AI pipeline bị đẩy sang script ngoài
- repo hiện tại chỉ đọc kết quả sau khi script chạy xong

### 9.4. Global `_pipeline_instance` là state dùng chung trong process

Pipeline được giữ ở biến global:

- build ở `build_gallery_from_dataset()`
- dùng lại ở `recognize_attendance()` và `process_video_tracklet()`

Điều này đơn giản cho demo nhưng có rủi ro nếu:

- nhiều user/session chạy song song
- model/gallery khác nhau cùng tồn tại

Nguồn:

- `core_app/views.py:22-23`
- `core_app/views.py:260-266`
- `core_app/views.py:324-330`
- `core_app/views.py:712-713`

---

## 10. Tóm tắt trả lời đúng trọng tâm câu hỏi

Nếu hỏi:

> “luồng pipeline chạy video và đẩy qua AI để điểm danh đang được xử lý như thế nào?”

thì câu trả lời chính xác nhất là:

1. Repo có một nhánh video nội bộ `POST /api/video/process/`:
   - đọc video theo frame,
   - detect nhiều mặt,
   - align,
   - extract embedding bằng model EdgeFace,
   - so với gallery embeddings,
   - tracking face qua nhiều frame,
   - trả kết quả phân tích cho frontend.

2. Repo có thêm một nhánh `POST /api/video/run/`:
   - không xử lý AI trực tiếp trong Django,
   - mà gọi script ngoài `import_group_video_to_tracks.py`,
   - rồi đọc `manifest.json` và `summary.txt`.

3. Tuy nhiên, phần “điểm danh” theo nghĩa ghi attendance record xuống DB hiện **mới hoàn chỉnh ở luồng ảnh đơn `POST /api/recognize/`**.

4. Với video, repo hiện mới dừng ở mức:
   - nhận diện theo frame,
   - tracking,
   - trả kết quả/preview,
   - hoặc bridge sang pipeline ngoài.

Chưa thấy logic hoàn chỉnh để:

- gom kết quả theo track thành một attendance event cuối cùng,
- tránh trùng,
- và ghi `AttendanceRecord` trực tiếp từ video trong repo này.

---

## 11. File cần đọc nếu muốn đào sâu tiếp

- `core_app/views.py`
- `core_app/video_processor.py`
- `core_app/face_recognition_engine.py`
- `core_app/utils.py`
- `core_app/models.py`

Nếu muốn lần tiếp nhánh video external, cần bổ sung source của:

- `Attendance_Workspace/scripts/import_group_video_to_tracks.py`
- toàn bộ thư mục `Attendance_Workspace/3_edgeface_training`
