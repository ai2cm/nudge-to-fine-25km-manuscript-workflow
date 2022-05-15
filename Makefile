# See https://stackoverflow.com/questions/53382383/makefile-cant-use-conda-activate
SHELL=/bin/bash
CONDA_ACTIVATE=source $$(conda info --base)/etc/profile.d/conda.sh ; conda activate ; conda activate
FIGURES = figure-01 figure-05 figure-08 figure-10 figure-11

# TODO: pin the versions of faceted, proplot, and xhistogram
create_environment:
	make -C fv3net update_submodules && \
		make -C fv3net create_environment && \
		( $(CONDA_ACTIVATE) fv3net-makefile ; pip install faceted ; pip install proplot ; pip install seaborn==0.11.2 ; pip install xhistogram )


post_process_simulations:
	python post_processing.py
	python metrics.py


create_figures: $(addprefix execute_notebook_, $(FIGURES))


execute_notebook_%:
	jupyter nbconvert --to notebook --execute notebooks/$**.ipynb