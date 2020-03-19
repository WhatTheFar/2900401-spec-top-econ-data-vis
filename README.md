# 2900401-spec-top-econ-data-vis

## Python Environment

### Setup a new environment

```sh
# install miniconda version
pyenv install miniconda3-4.3.30

# activate pyenv miniconda
pyenv activate miniconda3-4.3.30

# create anaconda environment
conda create -n spec-top-econ-data-vis anaconda

# activate anaconda
conda activate spec-top-econ-data-vis
```

### Activate the environment

```sh
source ./pyenv.sh
```

### Requirements

```
conda install -c conda-forge wordcloud
```

## Jupyter Notebook (Optional)

```sh
source ./pyenv.sh

conda install -c conda-forge jupyter_contrib_nbextensions
jupyter contrib nbextension install

# autopep8
jupyter nbextension enable code_prettify/autopep8

# vim_binding
cd $(jupyter --data-dir)/nbextensions
git clone https://github.com/lambdalisue/jupyter-vim-binding vim_binding
jupyter nbextension enable vim_binding/vim_binding
```
