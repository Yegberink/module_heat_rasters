"""Prepare the NUTS-3 regions overlapping a user shape case."""


rule prepare_nuts3:
    input:
        shapes="<shapes>",
        nuts3=rules.download_nuts3.output.geojson,
    output:
        regions="<resources>/automatic/{shapes}/nuts3.parquet",
    log:
        "<logs>/{shapes}/prepare_nuts3.log",
    conda:
        "../envs/module.yaml"
    script:
        "../scripts/prepare_nuts3.py"
