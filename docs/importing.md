# Importing data

`POST /api/v1/import/preview` validates CSV or JSON without writing records. `POST /api/v1/import` commits accepted records and returns rejected row numbers and reasons. Imports accept at most 10,000 rows and 4.5 MB per request.

Common aliases are detected, including `prompt_tokens` to `input_tokens`, `completion_tokens` to `output_tokens`, `app` to `application`, `vendor` to `provider`, and `model_name` to `model`. Explicit mappings take precedence.
