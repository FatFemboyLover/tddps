# Машины и наблюдатели — спецификация датасета

Документ описывает 6 типов машин, их категориальные признаки, набор наблюдаемых полей (`active_fields`), алфавит `status` и то, как именно 18 наблюдателей распределены по полям. Актуален для `generate.py` из последнего рефакторинга.

---

## 1. Общая картина

- **6 машин**, по одной на каждый тип (`machine_id` = 1…6).
- **18 наблюдателей**, по **3 на машину**; `observer_id = (machine_id − 1) × 3 + {1, 2, 3}`.
- Наблюдатели одного станка имеют **различные** наборы полей; их объединение равно `common ∪ active_fields(тип)`.
- Каждый наблюдатель **всегда** снимает 3 общих поля, плюс подмножество «дополнительных» полей из `active_fields` своего типа.
- В `observations` ячейка пуста, если поле либо не активно у типа, либо не назначено конкретному наблюдателю. В `ground_truth` все 10 полей всегда заполнены — это истинное состояние.

### Общие поля (снимают все 18 наблюдателей)

| Поле | Единица | σ шума |
|---|---|---:|
| `speed_rpm` | об/мин | 3 |
| `load_pct` | % | 0.25 |
| `motor_temp_c` | °C | 0.12 |

### Все 10 физических полей

`speed_rpm`, `load_pct`, `motor_temp_c` — общие; `current_a`, `voltage_v`, `power_kw`, `case_temp_c`, `vibration_x_mm_s`, `vibration_y_mm_s`, `vibration_z_mm_s` — дополнительные, доступны только если входят в `active_fields` типа.

---

## 2. Типы машин — сводная таблица

| `machine_id` | `slug` | `category` | `drive_type` | `cooling` | `criticality` | статусы (`status`) | кол-во доп. полей |
|---:|---|---|---|---|---|---|---:|
| 1 | `cnc-mill` | milling | spindle | liquid | high | `idle` → `warmup` → `running` | 5 |
| 2 | `lathe` | turning | spindle | liquid | medium | `idle` → `warmup` → `running` | 4 |
| 3 | `hydraulic-press` | pressing | hydraulic | passive | high | `releasing` → `holding` → `pressing` | 3 |
| 4 | `screw-compressor` | compressing | direct | liquid | high | `unloading` → `loading` → `loaded` | 6 |
| 5 | `conveyor-drive` | conveying | belt | air | low | `stopped` → `ramping` → `running` | 2 |
| 6 | `centrifugal-pump` | pumping | direct | liquid | medium | `idle` → `starting` → `pumping` | 5 |

---

## 3. Детали по каждому типу

### 3.1. `cnc-mill` (фрезерный, `machine_id=1`)

| Свойство | Значение |
|---|---|
| `category` / `drive_type` / `cooling` / `criticality` | milling / spindle / liquid / **high** |
| `active_fields` | `current_a`, `voltage_v`, `power_kw`, `vibration_x_mm_s`, `vibration_y_mm_s` |
| `status` (алфавит) | `idle` (<20%), `warmup` (20–30%), `running` (≥30%) |
| Обороты | 1000 + 22·load ± 90 (период 23 с) |
| Нагрузка | 55 ± 22 (75 с) ± 8 (9 с) |
| Напряжение | 400 ± 3 (17 с) |
| Температура двигателя | 50 ± 9 (лаг 0.8 с) |
| Температура корпуса | 37 ± 6 (лаг 1.3 с) |
| Вибрация | база 0.60 + 0.018·load; X доминирует (gain 1.00) |

Наблюдатели 1, 2, 3. `vibration_z_mm_s` и `case_temp_c` **не снимаются**.

### 3.2. `lathe` (токарный, `machine_id=2`)

| Свойство | Значение |
|---|---|
| `category` / `drive_type` / `cooling` / `criticality` | turning / spindle / liquid / medium |
| `active_fields` | `current_a`, `voltage_v`, `power_kw`, `vibration_x_mm_s` |
| `status` | `idle` (<25%), `warmup` (25–35%), `running` (≥35%) |
| Обороты | 1400 + 14·load ± 40 (период 19 с) |
| Нагрузка | 48 ± 30 (48 с) ± 5 (6.5 с) — высокая амплитуда |
| Напряжение | 400 ± 2 (23 с) |
| Температура двигателя | 44 ± 11 (лаг 1.1 с) |
| Температура корпуса | 33 ± 8 (лаг 1.6 с) |
| Вибрация | база 0.45 + 0.030·load; X доминирует (gain 1.20) |

Наблюдатели 4, 5, 6. Снимаются только X-вибрации; `case_temp_c`, `vibration_y_mm_s`, `vibration_z_mm_s` — нет.

### 3.3. `hydraulic-press` (гидравлический пресс, `machine_id=3`)

| Свойство | Значение |
|---|---|
| `category` / `drive_type` / `cooling` / `criticality` | pressing / hydraulic / passive / **high** |
| `active_fields` | `current_a`, `voltage_v`, `vibration_z_mm_s` |
| `status` | `releasing` (<40%), `holding` (40–70%), `pressing` (≥70%) |
| Обороты | 300 + 6·load ± 10 (период 31 с) |
| Нагрузка | 82 ± 12 (120 с) ± 3 (14 с) — очень высокая |
| Напряжение | 405 ± 4 (37 с) |
| Температура двигателя | 58 ± 6 (лаг 2.2 с) — большая тепловая инерция |
| Температура корпуса | 41 ± 4 (лаг 2.8 с) |
| Вибрация | база 1.10 + 0.008·load; **Z доминирует** (gain 1.30) |

Наблюдатели 7, 8, 9. Снимаются только Z-вибрации. `power_kw`, `case_temp_c`, `vibration_x/y_mm_s` — нет.

### 3.4. `screw-compressor` (винтовой компрессор, `machine_id=4`)

| Свойство | Значение |
|---|---|
| `category` / `drive_type` / `cooling` / `criticality` | compressing / direct / liquid / **high** |
| `active_fields` | `current_a`, `voltage_v`, `power_kw`, `case_temp_c`, `vibration_x_mm_s`, `vibration_y_mm_s` |
| `status` | `unloading` (<30%), `loading` (30–45%), `loaded` (≥45%) |
| Обороты | 3600 + 3·load ± 15 (период 41 с) — почти постоянные |
| Нагрузка | 70 ± 5 (300 с) ± 1.5 (22 с) — медленный цикл |
| Напряжение | 400 ± 1.5 (29 с) |
| Температура двигателя | 63 ± 4 (лаг 3.1 с) — самый горячий тип |
| Температура корпуса | 46 ± 3 (лаг 3.6 с) |
| Вибрация | база 0.80 + 0.005·load; **изотропная** (все gain = 1.10) |

Наблюдатели 10, 11, 12. Единственный тип, у которого снимается `case_temp_c`. Z-вибрации нет.

### 3.5. `conveyor-drive` (привод конвейера, `machine_id=5`)

| Свойство | Значение |
|---|---|
| `category` / `drive_type` / `cooling` / `criticality` | conveying / belt / air / **low** |
| `active_fields` | `current_a`, `voltage_v` |
| `status` | `stopped` (<10%), `ramping` (10–25%), `running` (≥25%) |
| Обороты | 250 + 4·load ± 5 (период 60 с) — самый тихоходный |
| Нагрузка | 28 ± 18 (90 с) ± 6 (7 с) — самая низкая |
| Напряжение | 400 ± 2.5 (33 с) |
| Температура двигателя | 38 ± 5 (лаг 0.6 с) — самая холодная |
| Температура корпуса | 29 ± 4 (лаг 1.0 с) |
| Вибрация | база 0.30 + 0.010·load; X доминирует (gain 1.30) |

Наблюдатели 13, 14, 15. **Минимальная оснастка**: только ток и напряжение. Тепловые и вибрационные поля не снимаются вообще.

### 3.6. `centrifugal-pump` (центробежный насос, `machine_id=6`)

| Свойство | Значение |
|---|---|
| `category` / `drive_type` / `cooling` / `criticality` | pumping / direct / liquid / medium |
| `active_fields` | `current_a`, `voltage_v`, `power_kw`, `vibration_y_mm_s`, `vibration_z_mm_s` |
| `status` | `idle` (<35%), `starting` (35–55%), `pumping` (≥55%) |
| Обороты | 1750 + 6·load ± 20 (период 27 с) |
| Нагрузка | 62 ± 20 (55 с) ± 7 (8 с) |
| Напряжение | 398 ± 3.5 (21 с) |
| Температура двигателя | 47 ± 10 (лаг 0.9 с) |
| Температура корпуса | 35 ± 7 (лаг 1.5 с) |
| Вибрация | база 0.55 + 0.022·load; **Y доминирует** (gain 1.40) |

Наблюдатели 16, 17, 18. Снимаются Y и Z вибрации; X — нет, `case_temp_c` — нет.

---

## 4. Как назначаются дополнительные поля наблюдателям

Для каждого типа `make_observer_masks` берёт список extras (индексы `active_fields` в `FIELDS`), перемешивает его RNG-ом с `seed`, и раздаёт наблюдателям:

- **Если extras = 2** (конвейер): `obs1 = {e0}`, `obs2 = {e1}`, `obs3 = {e0, e1}` — покрытие полное, наборы различны.
- **Если extras ≥ 3**: первые три идут по одному в `obs1..obs3`, остальные раскидываются по случайно выбранному наблюдателю (0, 1 или 2). Итог: все три набора различны, объединение = все extras.

Общие поля `speed_rpm`, `load_pct`, `motor_temp_c` **всегда** добавляются ко всем трём наборам.

**Важно:** распределение зависит от `--seed`. Для конкретной выгрузки его читаем из `observers.csv`, а не угадываем.

### Как посмотреть для своего датасета

```bash
python -c "
import csv
with open('data-100k/observers.csv') as f:
    for r in csv.DictReader(f):
        print(f\"{r['observer_id']:>3}  machine={r['machine_id']}  {r['observed_fields']}\")
"
```

Или одной командой с типами машин:

```bash
python -c "
import csv
types = {r['machine_id']: r['name'] for r in csv.DictReader(open('data-100k/machines.csv'))}
for r in csv.DictReader(open('data-100k/observers.csv')):
    m = r['machine_id']
    print(f\"obs{r['observer_id']:>3}  {types[m]:<22}  {r['observed_fields']}\")
"
```

Пример вывода (раскладка для `seed=42` — конкретные значения читайте из файла, они зависят от seed):

```
obs  1  cnc-mill-01            speed_rpm|load_pct|motor_temp_c|current_a|vibration_x_mm_s
obs  2  cnc-mill-01            speed_rpm|load_pct|motor_temp_c|voltage_v|vibration_y_mm_s
obs  3  cnc-mill-01            speed_rpm|load_pct|motor_temp_c|power_kw|vibration_x_mm_s|vibration_y_mm_s
...
obs 13  conveyor-drive-05      speed_rpm|load_pct|motor_temp_c|current_a
obs 14  conveyor-drive-05      speed_rpm|load_pct|motor_temp_c|voltage_v
obs 15  conveyor-drive-05      speed_rpm|load_pct|motor_temp_c|current_a|voltage_v
```

У конвейера `active_fields = {current_a, voltage_v}` — ровно 2 extras, поэтому раскладка жёсткая (без случайности): `{current_a}`, `{voltage_v}`, `{current_a, voltage_v}`.

---

## 5. Сводная матрица «тип × поле»

`✓` — поле активно у типа (снимается хотя бы одним наблюдателем), `·` — не снимается ни одним.

| Тип | speed | load | motor | current | voltage | power | case | vib X | vib Y | vib Z |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| cnc-mill | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | ✓ | ✓ | · |
| lathe | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | ✓ | · | · |
| hydraulic-press | ✓ | ✓ | ✓ | ✓ | ✓ | · | · | · | · | ✓ |
| screw-compressor | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · |
| conveyor-drive | ✓ | ✓ | ✓ | ✓ | ✓ | · | · | · | · | · |
| centrifugal-pump | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | · | ✓ | ✓ |

Колонки `speed`/`load`/`motor` — общие для всех типов по построению. Колонка `current` и `voltage` есть у всех — это важно для `detect.py`, который проверяет ток по всем наблюдателям. Остальные поля — предмет варьирования типа.