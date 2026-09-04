In this module I would like to develop rasters for disaggregating heat.

some general information:
- any assumptions made should be in config/config.yaml
- rules should go in workflow/rules/{snakefiles}.smk. Separate snakefiles per part of the processing
- scripts go in workflow/scripts/{script}.py
- There should be schema validation for all input and output files in _schemas.py. This makes sure that it is not necessary to do any checking of the throughput since input and output adhere to the correct schema. 
- Write no defensive code. If the code does not work it should break and not silently continue. 
- There should be no globals or python functions in the snakefiles containing rules. These should be in _utils.smk
- Write as few lines of code to make the code work. Check that there is no unnecessary code every time you finish answering. Do however write proper annotation of the code within the scripts so people understand what they're looking at. 
- As a general rule make testing short. You can run some quick test but the actual testing I would like to do myself. 
- Do not alter integration tests unless specifically asked for. 
