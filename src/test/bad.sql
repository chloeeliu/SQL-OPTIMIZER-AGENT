SELECT *
FROM mimiciv_icu.icustays i
JOIN mimiciv_hosp.labevents l
  ON l.subject_id = i.subject_id AND l.hadm_id = i.hadm_id
WHERE i.stay_id = 30008792
  AND l.charttime BETWEEN i.intime AND i.outtime;
