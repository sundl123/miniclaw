In the first lesson, you saw how skills work with Claude AI.
0:03
Now, we'll work with the Claude API
0:05
to test the two skills we made from the previous lesson.
0:08
To use skills with the Claude API,
0:11
we'll need to use the code execution tool and the files API.
0:15
This will equip Claude with file system access
0:18
for reading and writing files and with bash for executing code.
0:21
Let's get to it. We've talked quite a bit
0:24
about how skills work and how to create them.
0:27
And we talked a little bit
0:29
as well about the portability of skills
0:31
across different environments in the Claude ecosystem,
0:34
as well as many other agentic applications.
0:37
We started by looking at skills in Claude AI and Claude Desktop,
0:41
and now we're going to move to talk about
0:43
how to use skills using the Claude Messages API.
0:45
There are two things that are important to note.
0:47
First, skills that you create in Claude AI and Claude Desktop
0:52
are not shared in The Claude API or Claude Code.
0:56
The second important piece is that in order for skills to work,
1:00
we need the ability for Claude to execute code,
1:03
create and edit documents, presentations, PDFs,
1:06
and data reports, and work with a file system.
1:10
This is something that we're going to have to manually do
1:12
when we work with the Claude API.
1:13
And this is something that is actually configured for you
1:16
right away when using Claude AI and Claude Desktop.
1:20
In Claude Desktop or Claude AI
1:22
If I go to settings
1:24
and I take a look at the capabilities,
1:27
you can see here that there's a section
1:29
for code execution and file creation.
1:31
This is what we're going to talk about in more depth
1:33
when we work with the API directly.
1:35
But this is a setting that is enabled by default
1:39
that allows Claude to execute code, create docs, spreadsheets, presentations, and more.
1:43
This essentially gives Claude AI and Claude Desktop
1:46
a computer or a virtual machine
1:49
to execute code and perform all those tasks that make Skills happen.
1:53
If this is disabled, we'll actually see
1:56
that we need to turn this on
1:58
to even be able to use skills.
2:00
Now let's shift back and talk a little bit
2:03
about how this code execution tool and file creation works,
2:06
because we're going to need to enable
2:08
this manually when we work with the API.
2:11
When working with tools like Claude Code and the Claude agent,
2:15
you have direct access to a file system.
2:17
Whereas using the Claude API, we do not,
2:20
and need a container to execute code
2:22
and a file system to work with.
2:24
Claude AI and Claude Desktop,
2:26
that containerized environment and file system
2:29
is given to you and not something you have to implement.
2:32
At the end of the day, the functionality is all the same,
2:35
but the way in which we utilize skills is slightly different.
2:38
The skills themselves do not change,
2:41
the format of those skills do not change,
2:43
but depending on the environment that you're in,
2:45
you may utilize the way in which skills work slightly differently.
2:49
As we start to explore the Messages API,
2:51
we're going to use the code execution tool.
2:54
The code execution tool allows Claude to run
2:57
Bash or shell commands
2:59
to perform all these actions that we saw
3:02
when working with skills. Creating, viewing, editing files,
3:05
and writing code, all in a sandboxed environment.
3:08
The code execution tool
3:10
gives our application the ability
3:13
to have a separate dedicated container
3:15
to execute code and work with a file system.
3:18
as you've seen with all the things that skills can do,
3:21
that is mission critical for reading our skills,
3:24
executing code within those skills, and working with other files
3:28
that we might want to edit and view and create.
3:30
To give you a visualization of what this looks like,
3:33
when we include the code execution tool,
3:36
we give Claude an execution sandbox or a container.
3:40
When we ask Claude to create and execute files,
3:43
these are executed in a safe and isolated environment.
3:47
There are limitations for the RAM, the disk, the CPU,
3:51
and more importantly, there is no internet connection provided
3:54
and there are pre-installed libraries that you get out of the box.
3:58
So this does not work with every single kind of coding environment.
4:01
There are some limitations here to be mindful of.
4:04
At the same time, we also get access to a file system
4:06
that we can start adding directories to.
4:09
You might have even seen hints of that
4:11
when we worked with Claude desktop and Claude AI.
4:14
This limitation of no internet connection
4:16
is something that is specific to the Messages API.
4:19
When we're using the code execution tool
4:21
in Claude AI or Claude desktop,
4:23
we do have access to an internet connection
4:26
and we can download and install packages.
4:28
The Code Execution Tool works quite nicely
4:31
with another set of APIs that the
4:33
Claude API allows us to work with.
4:35
As you can imagine, when we're working with files,
4:38
adding, creating, writing, modifying files,
4:42
we need some mechanism for actually storing those underlying files.
4:46
The Claude API includes a set of APIs called the Files API
4:50
to upload and download files
4:52
that can be run and worked on inside of the container.
4:56
You can imagine a scenario where
4:58
the user asks to summarize some input
5:00
and save the summary to a text file.
5:03
We upload that input file,
5:05
send it to the container, download generated files
5:08
with this Files API. We're going
5:10
to be seeing this shortly in code.
5:12
When we see the IDs that we get back
5:13
from uploading and downloading files
5:15
and how this works nicely with skills
5:18
and our Code Execution Tool.
5:20
And this is exactly where skills come into play.
5:23
The library of skills that we get
5:26
out of the box in tools like Claude AI
5:28
or that we can include if we want using the API,
5:32
those live in a directory that are powered in the container.
5:35
As we start to read from this skills directory,
5:38
as we start to add information to our skills
5:41
or use those underlying skills to create new files
5:44
that we can download or upload,
5:46
this is where skills come into play.
5:48
And we're going to see a requirement when working with the API,
5:51
when we want to use skills, we need
5:53
to use the Code Execution Tool as well.
5:56
Now that we have a good
5:57
sense of what the Code Execution Tool
5:59
and Files API allow us to do,
6:01
let's see how to use this in action.
6:03
We're going to go and revisit the two previous custom skills
6:06
that we built for generating practice
6:08
questions as well as time series analysis.
6:11
So let's head over to a Jupyter notebook and explore this.
6:14
Right here, I have my two
6:15
custom skills that we've worked with before.
6:18
I also have a folder for
6:19
data that I'm going to be using
6:21
to analyze time series data.
6:23
I also have a folder for lecture notes that I'll be using
6:26
when I use my generating practice questions skill.
6:29
To get started in this notebook,
6:31
I'm going to load the environment variables that I need
6:34
as well as a helper to help
6:36
me find particular files from a directory.
6:37
We're going to see this in
6:39
action when we start using our skills.
6:40
To start, I'm going to begin using my generating practice questions skill.
6:45
So let's go ahead and take a look
6:46
at the first part that I need to do.
6:49
To begin, I need to upload the skill directory.
6:52
Here you can see we're using that files_from_dir helper function,
6:55
as well as the necessary beta
6:57
headers for skills. Once this is done,
7:00
I should be able to see the skill ID that I've created.
7:04
This betas list are particular headers that I add when
7:08
I make a request to the Messages API.
7:10
Under the hood, these are turning into request headers
7:13
to make sure that I'm getting the right data back
7:15
and communicating appropriately with the API.
7:18
To take a look at all the skills that I have,
7:20
I can use this .list method,
7:22
and I'm going to pass in a source of custom
7:25
so that we don't load all the built-in skills
7:27
and instead just confirm that I've created the ones as expected.
7:32
And here I can see the title,
7:33
as well as the unique skill ID
7:35
that I'm going to be using shortly.
7:37
In order for this to work as expected,
7:39
we're going to need to make use of the LaTeX file
7:42
where we're going to generate practice questions from.
7:45
Here, I'll use the Files API
7:47
to upload this particular LaTeX file.
7:50
make sure that it's set for reading
7:52
and then get back a file object.
7:55
I'll be using this file object in conjunction with the skills necessary
8:00
to make sure that it's all
8:02
working as expected. I'm using Sonnet here,
8:05
and I'm passing in the necessary beta headers, not only for skills,
8:09
but in order for skills to work
8:11
as expected when talking to the model,
8:13
I need to make sure I
8:15
have the code execution beta as well.
8:17
And since I'm sending a file here, we have to
8:19
make sure we have the files API header as well.
8:22
When working with skills, these skills are
8:24
set in a keyword argument called container,
8:26
and here is where I pass in the list of skills.
8:29
These could be custom ones or built-in ones.
8:32
As I create many different versions of the skills,
8:35
I can reference a particular timestamp
8:38
or just use the latest one that I have.
8:40
As I start to communicate with the model,
8:42
I ask it to generate practice questions
8:45
and then specify the file that I'm working with.
8:48
This file object was previously created
8:51
when I uploaded the LaTeX file.
8:53
We finally make sure we're bringing
8:54
in the correct tools for code execution.
8:56
and send a message to our API.
8:59
Now let's go take a look
9:00
at the response that we got back.
9:02
We can see here that there are multiple different pieces being used.
9:06
Tools on the server, code execution, additional tools being used,
9:10
and then finally, a bash code execution result.
9:13
To make this a little bit cleaner
9:15
to look at, let's add some nice formatting
9:17
so that we can go ahead and take a look
9:19
and analyze different text responses and tool use.
9:22
We're going to go ahead and see in this particular series
9:25
what's happening one step at a time.
9:27
When we take a look at what the response is,
9:29
which includes our text and our tool use and tool results,
9:32
the first thing the model is telling us
9:35
is it can help generate questions from these notes
9:37
and it's going to start by reading the skill file
9:39
and examining the lecture notes.
9:42
Notice here, it's detected the skill that it needs to use,
9:46
but it's only reading the SKILL.md
9:48
We're going to see later on if there
9:50
are additional files that need to be read,
9:52
we'll make use of that progressive disclosure.
9:55
We're also going to review in
9:56
our input that LaTeX file as well.
9:59
We're going to go ahead and see the underlying data
10:01
that comes from these files. This is the YAML front matter
10:04
that we've seen before, as well as the LaTeX
10:07
from our notes04.tex file.
10:09
Next, we're going to go ahead and check the markdown template
10:12
to use the proper structure because we
10:14
want our output to be in markdown.
10:16
Here is where we're going to leverage
10:18
a bit more of that progressive disclosure.
10:20
Here's where we're going to read inside of the assets folder
10:23
that markdown_template.md
10:26
We'll get back the response that we've read
10:28
and now we'll generate the questions
10:30
based on the lecture notes that we've passed.
10:32
Here we're going to use our code execution tool
10:35
to create a particular file.
10:37
We'll give that file text in markdown,
10:40
and we'll get back the result of that file.
10:42
We're going to go ahead and copy that to an output directory
10:46
and use our Files API to get back a file_id
10:49
that we can download later on.
10:52
Once we get back that result,
10:54
We can take a look at the underlying file that's been generated
10:57
and make use of that file ID to programmatically download it.
11:01
We can see here it's been saved and is ready for use.
11:05
Using that file ID that we saw above
11:07
Let's go ahead and download the file.
11:11
We'll go ahead and check in this response and
11:13
make sure that we have the file ID correctly extracted.
11:15
And if we have that, which we expect to do,
11:18
we should be able to download that particular file.
11:21
We'll go ahead and write to
11:23
a file called notes04.md with that content.
11:25
includes the file ID
11:28
as well as the necessary beta headers to communicate with the API.
11:32
We can see here, we've downloaded that notes04.md file,
11:36
and this is coming from the Files API
11:38
with the code execution tool,
11:40
all generated with the model and a skill.
11:43
Inside of this file that we've downloaded,
11:45
we can see that we're following those
11:47
exact parts that we had in the skill.
11:50
Starting with true and false questions,
11:52
moving on to explanatory questions, to coding questions,
11:55
and finally, to use case applications.
11:58
We can preview this in markdown
11:59
to see what that would look like.
12:01
And here we can see our
12:03
use case application, all the things necessary.
12:06
Now is a good time to evaluate this particular output.
12:09
Did we do exactly what the
12:10
skill wanted? It looks good to start.
12:12
bringing in some unit tests can
12:13
really take this to the next level.
12:15
If we need, we can go back and
12:17
modify the skill, just like we saw before,
12:19
using the API, the code execution
12:21
tool, and the Files API as well.
12:24
We also have the ability to delete skills programmatically.
12:27
In order to delete a skill, we
12:29
first have to find all of the versions
12:31
associated with that skill and then delete them.
12:34
Once those versions are deleted,
12:36
we should be able to delete the underlying skill. Right here.
12:41
Next, we're going to go ahead
12:42
and use our analyzing time series skill
12:44
alongside another skill.
12:46
This is going to look pretty familiar to what
12:48
we saw above, so let's go through these steps.
12:51
First, we're going to upload our custom skill.
12:53
get back a skill ID and
12:55
confirm that we've done that as expected.
12:58
Here, we can also see that
12:59
we're not loading only the custom skills,
13:01
we can see the built-in skills as well.
13:04
These should look pretty familiar, as we
13:05
saw them as well in Claude AI.
13:08
Next, we're going to go ahead and upload our input file.
13:11
This is going to be our retail sales CSV file.
13:14
We're going to build a message to send to the API,
13:16
and just like before, we're going
13:18
to go ahead and use our skill,
13:20
but here we're also going to include the docx skill as well.
13:25
We're going to use this because we want to
13:28
create a word doc summarizing the results and the plots.
13:30
So here we're seeing a combination of custom skills
13:33
with the skill ID that we have as well as the version.
13:36
and using Anthropic built-in skills
13:39
in this case, the docx skill.
13:42
We're passing in the same headers
13:43
that we had to pass in before,
13:45
skills, code execution, and the files API.
13:49
Now that this is finished running,
13:51
we can examine the particular type of response that we get.
13:55
We're going to see something similar to what we saw before,
13:57
but this time there's just a little bit more happening.
14:00
Let's go and see what's happening
14:02
under the hood with our nice formatting.
14:04
So here, the model is going to respond
14:06
by helping us analyze time series data.
14:09
And just like before, we're going to start reading
14:11
the entirety of these SKILL.md files.
14:14
We're going to read our custom skill as well as the built-in
14:17
docx skill, which we're going to need to use.
14:19
We can see the result of those include the content,
14:22
starting from the beginning of the file
14:24
and including the entire SKILL.md
14:27
Next, we're going to go ahead and examine the data
14:29
to run our time series analysis.
14:31
We're going to look at just
14:32
the first 20 lines of this CSV
14:34
to examine the names of the columns
14:37
and the type of data that we're working with.
14:39
Since this is working as expected,
14:42
we're going to go ahead and run the diagnostics
14:45
and create the visualizations.
14:47
These particular commands that we need to run
14:49
are coming directly from our skill.
14:52
Here is where we're going to go ahead, read those underlying files,
14:55
execute that code and hand that back to Claude to work with.
15:00
We're going to get back the result of these executions.
15:03
We're going to get that back for diagnostics as well as visualize.
15:07
We're then going to read the summary and diagnostics,
15:10
which is the result of our script
15:13
that comes in a file called summary.txt
15:16
Once we have that particular file created,
15:19
we can then go ahead and create a Word document.
15:22
The built-in docx skill
15:24
includes the correct content for how to work with Word docs.
15:28
We're going to go ahead and take a look
15:30
at how best to generate that document
15:33
and leverage progressive disclosure here.
15:35
We don't need everything from the docx skill,
15:38
just using a way to get to those markdown files.
15:41
Once we have that, we'll create a comprehensive Word document
15:45
using the skill necessary, execute the code to make it do that,
15:49
and generate the underlying Word document.
15:51
Once we have that Word document,
15:53
we'll copy that to the output directory
15:55
and just like we saw before, get back a file ID
15:58
that we can use if we want to download this Word document.
16:02
We can see a summary of what this data looks like.
16:05
And now we can download the file.
16:07
Similarly, we'll go ahead and find that file_id if it exists.
16:10
We're going to go ahead and download that particular file
16:13
with the necessary contents as a docx file.
16:17
If we take a look at what this looks like,
16:19
we now have a Word document
16:21
with our findings, our overview, our statistics.
16:24
We can see that we brought in those plots and visualizations,
16:27
as well as the statistical analysis that we've requested.
16:31
This is also a great time to not only evaluate
16:33
if what we're doing is expected in the skill,
16:36
but that we're doing this in a predictable fashion.
16:40
As we continue to evaluate, we can always
16:42
modify this skill as much as we want.
16:44
But all this data is coming in from the skill
16:47
as well as the docx skill.
16:49
to create this individual file.
16:52
Like we saw before, if we want to delete this skill,
16:54
we can list all the versions and delete all those versions.
16:58
And once those versions are deleted,
17:00
delete the underlying skill. In this lesson,
17:03
We've combined our knowledge of the Messages API,
17:06
the Code Execution tool, the Files API, and skills
17:09
to take our custom skills and work with them programmatically.
17:13
In the next lesson, we're going to move to Claude code
17:16
and see how to add our own custom skills
17:19
inside of a .claude folder
17:21
and build a more sophisticated command line application.