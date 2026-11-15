# Metric contract (khai báo bắt buộc — chốt ở phút 30, trước khi chạy eval)

> Các metric chuẩn đã được cài trong `src/metrics/tracks.py`. File này là nơi nhóm **cam kết** cách dùng chúng.
> Không đổi testset, threshold hay trọng số sau khi đã thấy kết quả eval.

| Mục | Khai báo của nhóm |
|---|---|
| Track | T02 · Raw QC Triage |
| Primary metric (tên đúng như evaluator in ra) | Defect Recall@B (B=20) |
| Tăng tốt hay giảm tốt? | higher |
| Đơn vị đánh giá (image / region / pair / release / batch / case …) | image |
| Công thức + numerator / denominator | Số ảnh lỗi trong top-20 / tổng số ảnh lỗi trong split eval |
| Cách ghép prediction ↔ GT (IoU? id? tolerance?) | Ghép chính xác theo `image_id`; xếp `score` giảm dần |
| Candidate pool cố định | `fixtures/t02_raw_qc/images.csv`; evaluator lọc split eval |
| Review budget B / K | B=20 |
| Seed | 42 |
| Threshold policy (chọn trên dev như thế nào) | Không học ngưỡng; score cố định = 0.55×blur risk + 0.30×dark risk + 0.15×glare risk. Trọng số chốt trước eval. |
| Eval split (không dùng để tune) | `eval` trong `images.csv`, chia theo cảnh gốc |
| Chỉ số lỗi xấu (miss / false alarm / false reject) | Defect miss; false alarm trong top-20 |
| Slices sẽ báo cáo (≥2) | `light` (day/dusk/night), `camera_id` |
| Cách báo độ bất định khi N nhỏ (Wilson CI / bootstrap) | Evaluator hiện không xuất CI; báo numerator/denominator và N, không suy diễn độ chắc chắn |
| Ngày giờ chốt + người chốt | 2026-11-15 · Trinh Xuan Toan |

Nếu baseline = 0 thì ghi rõ "baseline = 0" thay vì phần trăm cải thiện.
