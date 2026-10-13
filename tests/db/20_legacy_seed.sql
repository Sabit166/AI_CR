-- Synthetic legacy rows reproducing the inconsistencies seen in production:
-- mixed code formats, title spellings, teacher-name variants, exam-type spellings,
-- empty strings instead of NULL, plus rows that must NOT be migrated.
insert into public."Exams" (id, "Course Code", "Course Title", "Course Teacher", "Class Section", "Exam Type", "Exam Day", "Exam Date", "Syllabus", "Exam Notes Drive Link") values
  (1, 'CSE-415', 'Human Computer Interface', 'Major Nazmul', 'A', 'Class Test Two', 'Monday', '2026-08-03 08:00:00', 'Chapter Two full ', ''),
  (3, 'GEEM 433', 'Ethics and Morality', 'Arif Bhuiyan', 'B', 'Mid', 'Thursday', '2026-08-06 08:00:00', 'Chapter 2 full and 3 half', ''),
  (4, 'CSE-464', 'Software Development Project II', 'Nafisa Maliyat', '', 'Project Update', 'Tuesday', '2026-08-04 08:00:00', 'Frontend', ''),
  (5, 'CSE 427', 'Digital Image Processing', 'Shahriar Sazzad', 'A', 'Class Test 2', 'Monday', '2026-08-10 08:00:00', '', 'https://drive.example.com/x'),
  (6, 'CSE-464', 'Software Development Project-2', 'Nafisa Nawal', '', 'Project Update', 'Tuesday', '2026-08-11 08:00:00', 'Frontend Update', ''),
  (7, 'CSE-415', 'Human Computer Interface', 'Maj Nazmul Hasan', 'B', 'MID', 'Thursday', '2026-08-13 08:00:00', '', ''),
  -- not migratable: unparseable code, unknown type, type invalid for course
  (8, 'Lab', 'Mystery', null, null, 'CT 1', null, '2026-08-20 08:00:00', null, null),
  (9, 'CSE-415', 'Human Computer Interface', null, null, 'Viva', null, '2026-08-21 08:00:00', null, null),
  (10, 'CSE-464', 'Software Development Project II', null, null, 'CT 1', null, '2026-08-22 08:00:00', null, null);
select setval(pg_get_serial_sequence('public."Exams"', 'id'), 100);
