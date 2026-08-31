In this module I would like to calculate district heating potentials and costs based on this approach: [https://www-sciencedirect-com.tudelft.idm.oclc.org/science/article/pii/S0306261923015180?utm_source=chatgpt.com#bb0150](https://www-sciencedirect-com.tudelft.idm.oclc.org/science/article/pii/S0306261923015180?utm_source=chatgpt.com#bb0150). 

I want to link this to the following module: [https://github.com/modelblocks-org/module_euro_building_heat](https://github.com/modelblocks-org/module_euro_building_heat) to provide the heat demand base layer. 

In the future this module should be linked with a spatially explicit heat supply module including waste heat and geothermal energy. 

some general information:
- any assumptions made should be in config/config.yaml
- rules should go in workflow/rules/{snakefiles}.smk. Separate snakefiles per part of the processing
- scripts go in workflow/scripts/{script}.py
- There should be schema validation for all input and output files in _schemas.py. This makes sure that it is not necessary to do any checking of the throughput since input and output adhere to the correct schema. 
- Write no defensive code. If the code does not work it should break and not silently continue. 
- There should be no globals or python functions in the snakefiles containing rules. These should be in _utils.smk
- Write as few lines of code to make the code work. Check that there is no unnecessary code every time you finish answering. 
- As a general rule make testing short. You can run some quick test but the actual testing I would like to do myself. 
- Do not alter integration tests unless specifically asked for. 
